import logging
import os
import uuid
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Strictly allowed final extensions (legacy .doc and .ppt dropped per Requirement 8)
ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "txt",
    "png",
    "jpg",
    "jpeg",
}

# Dangerous intermediate extension segments (e.g. homework.exe.pdf)
DANGEROUS_INTERMEDIATE_EXTENSIONS = {
    "exe",
    "bat",
    "cmd",
    "sh",
    "php",
    "py",
    "js",
    "vbs",
    "scr",
    "com",
    "pif",
    "msi",
    "ps1",
    "jar",
    "cgi",
    "pl",
    "asp",
    "aspx",
    "vbe",
    "wsf",
    "wsh",
}

# RTL and bidirectional override characters to strip
RTL_OVERRIDE_CHARS = {
    "\u202e",  # Right-to-Left Override
    "\u202b",  # Right-to-Left Embedding
    "\u202a",  # Left-to-Right Embedding
    "\u202c",  # Pop Directional Formatting
    "\u202d",  # Left-to-Right Override
    "\u200e",  # Left-to-Right Mark
    "\u200f",  # Right-to-Left Mark
}


def sanitize_display_filename(filename: str) -> str:
    """
    Sanitize human-readable display filenames:
    - Preserves Unicode characters (Nepali Devanagari, accented Latin, etc.)
    - Strips directory path separators (/ and \\)
    - Strips ASCII control characters (0-31, 127)
    - Strips directional override characters including U+202E
    - Caps filename stem length to prevent display overflow
    """
    if not filename:
        return "submission_file"

    # 1. Strip path separators
    clean_name = os.path.basename(filename.replace("\\", "/"))

    # 2. Strip control characters
    clean_name = "".join(ch for ch in clean_name if ord(ch) >= 32 and ord(ch) != 127)

    # 3. Strip RTL / directional override characters
    clean_name = "".join(ch for ch in clean_name if ch not in RTL_OVERRIDE_CHARS)

    # 4. Strip leading/trailing dots and spaces
    clean_name = clean_name.strip(" .")
    if not clean_name:
        return "submission_file"

    # 5. Cap length while preserving extension
    stem, ext = os.path.splitext(clean_name)
    if len(stem) > 100:
        stem = stem[:100]

    return f"{stem}{ext}" if ext else stem


def validate_filename_extensions(filename: str) -> str:
    """
    Validates final extension and checks for dangerous intermediate extensions.
    Returns the lowercased final extension without leading dot.
    """
    clean_name = os.path.basename(filename.replace("\\", "/"))
    parts = clean_name.split(".")

    if len(parts) < 2:
        raise ValidationError(_("Uploaded file must have an extension."))

    final_ext = parts[-1].lower().strip()
    if final_ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            _(
                "File extension '.%(ext)s' is not supported. Allowed formats: PDF, DOCX, PPTX, TXT, PNG, JPG."
            ),
            params={"ext": final_ext},
        )

    # Check intermediate parts for dangerous executable extensions (e.g. homework.exe.pdf)
    intermediate_parts = [p.lower().strip() for p in parts[1:-1]]
    for part in intermediate_parts:
        if part in DANGEROUS_INTERMEDIATE_EXTENSIONS:
            raise ValidationError(
                _(
                    "Filenames containing dangerous intermediate extensions ('.%(part)s') are strictly prohibited."
                ),
                params={"part": part},
            )

    return final_ext


def submission_file_path(instance, filename: str) -> str:
    """
    Generate an unguessable randomized file path within the private storage.
    """
    ext = Path(filename).suffix.lower()
    random_filename = f"{uuid.uuid4().hex}{ext}"
    return os.path.join("submissions", random_filename)


def assignment_attachment_path(instance, filename: str) -> str:
    """
    Generates a secure, collision-resistant storage path for assignment attachments:
    assignments/assignment_<id>/<uuid4>_<sanitized_name>
    """
    clean_name = sanitize_display_filename(filename)
    unique_id = uuid.uuid4().hex
    assignment_id = (
        instance.assignment_id
        if hasattr(instance, "assignment_id") and instance.assignment_id
        else "temp"
    )
    return f"assignments/assignment_{assignment_id}/{unique_id}_{clean_name}"


def validate_submission_file(file) -> None:
    """
    Validates submission file size, extension allowlist, dangerous intermediate
    extensions, and real binary content (magic bytes and internal structures).
    """
    if not file:
        return

    # 1. Size Check
    max_size = getattr(settings, "ASSIGNMENT_MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)
    if file.size > max_size:
        max_mb = max_size // (1024 * 1024)
        raise ValidationError(
            _("File size exceeds the %(max_mb)s MB limit."),
            params={"max_mb": max_mb},
        )

    # 2. Filename and Extension Validation
    filename = getattr(file, "name", "")
    final_ext = validate_filename_extensions(filename)

    # 3. Read Header & Check Global Binary Executable Signatures
    file.seek(0)
    header = file.read(2048)
    file.seek(0)

    # Reject DOS PE executables (MZ) and Linux ELF binaries
    if header.startswith(b"MZ") or header.startswith(b"\x7fELF"):
        raise ValidationError(_("Executable binary files are strictly prohibited."))

    # 4. Content Validation by Type
    if final_ext == "pdf":
        _validate_pdf_content(file, header)
    elif final_ext in ("png", "jpg", "jpeg"):
        _validate_image_content(file, final_ext, header)
    elif final_ext in ("docx", "pptx", "xlsx"):
        _validate_office_archive(file, final_ext, header)
    elif final_ext == "txt":
        _validate_text_content(file)

    # Always restore file read pointer
    file.seek(0)


def _validate_pdf_content(file, header: bytes) -> None:
    """
    Verify that file contains %PDF- within the first 1024 bytes (ISO 32000-1 §7.5.2).
    Tolerates optional leading UTF-8 BOM, whitespace, newlines, and comments.
    """
    idx = header[:1024].find(b"%PDF-")
    if idx == -1:
        filename = getattr(file, "name", "unknown")
        file_size = getattr(file, "size", 0)
        logger.warning(
            "PDF validation failed: missing %%PDF- marker in first 1024 bytes. filename=%s, size=%s",
            filename,
            file_size,
        )
        raise ValidationError(_("File content does not match a valid PDF document."))


def _validate_image_content(file, ext: str, header: bytes) -> None:
    """Verify image magic bytes, verify structure with Pillow, and cap dimensions."""
    if ext == "png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError(_("File content does not match PNG format."))
    elif ext in ("jpg", "jpeg"):
        if not header.startswith(b"\xff\xd8\xff"):
            raise ValidationError(_("File content does not match JPEG format."))

    max_dim = getattr(settings, "ASSIGNMENT_MAX_IMAGE_DIMENSION", 10000)
    max_pixels = getattr(settings, "ASSIGNMENT_MAX_IMAGE_PIXELS", 25_000_000)

    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()
            width, height = img.size
            if width > max_dim or height > max_dim:
                raise ValidationError(
                    _("Image dimensions (%(w)sx%(h)s) exceed the maximum allowed (%(max)spx)."),
                    params={"w": width, "h": height, "max": max_dim},
                )
            if width * height > max_pixels:
                raise ValidationError(
                    _("Image resolution exceeds the maximum allowed %(max_mp)s megapixels."),
                    params={"max_mp": max_pixels // 1_000_000},
                )
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError(_("Corrupted or invalid image file.")) from exc
    finally:
        file.seek(0)


def _validate_office_archive(file, ext: str, header: bytes) -> None:
    """
    Verify DOCX/PPTX zip archive structure:
    - Must start with PK\\x03\\x04
    - Must contain [Content_Types].xml and document/presentation root
    - Must not contain vbaProject.bin (macros)
    - Must not be password encrypted
    - Caps entry count and uncompressed total size (zip bomb mitigation)
    """
    if not header.startswith(b"PK\x03\x04"):
        raise ValidationError(_("Office document archive header is invalid."))

    max_entries = getattr(settings, "ASSIGNMENT_ZIP_MAX_ENTRIES", 1000)
    max_uncompressed = getattr(settings, "ASSIGNMENT_ZIP_MAX_UNCOMPRESSED_BYTES", 50 * 1024 * 1024)

    file.seek(0)
    try:
        with zipfile.ZipFile(file, "r") as zf:
            infolist = zf.infolist()

            if len(infolist) > max_entries:
                raise ValidationError(
                    _("Document archive exceeds maximum entry limit (possible archive bomb).")
                )

            total_uncompressed = sum(item.file_size for item in infolist)
            if total_uncompressed > max_uncompressed:
                max_mb = max_uncompressed // (1024 * 1024)
                raise ValidationError(
                    _(
                        "Document uncompressed size exceeds %(max_mb)s MB limit (possible archive bomb)."
                    ),
                    params={"max_mb": max_mb},
                )

            # Check for encryption / password
            for item in infolist:
                if item.flag_bits & 0x1:
                    raise ValidationError(
                        _("Password-protected or encrypted documents are not allowed.")
                    )

            namelist = zf.namelist()

            # Reject VBA macro project binaries
            for name in namelist:
                lower = name.lower()
                if lower.endswith("vbaproject.bin") or "vba" in lower.split("/"):
                    raise ValidationError(
                        _("Macro-enabled documents (.docm, .pptm, or embedded VBA) are forbidden.")
                    )

            # Verify required Office Open XML internal components
            names_set = set(namelist)
            if "[Content_Types].xml" not in names_set:
                raise ValidationError(
                    _("Invalid Office document archive: missing [Content_Types].xml.")
                )

            if ext == "docx" and "word/document.xml" not in names_set:
                raise ValidationError(_("Invalid Word document: missing word/document.xml."))

            if ext == "pptx" and "ppt/presentation.xml" not in names_set:
                raise ValidationError(
                    _("Invalid PowerPoint presentation: missing ppt/presentation.xml.")
                )

            if ext == "xlsx" and "xl/workbook.xml" not in names_set:
                raise ValidationError(_("Invalid Excel workbook: missing xl/workbook.xml."))
    except zipfile.BadZipFile as exc:
        raise ValidationError(_("Invalid or corrupted Office document file.")) from exc
    finally:
        file.seek(0)


def _validate_text_content(file) -> None:
    """
    Verify plain text file content:
    - Accepts UTF-8 (with or without BOM)
    - Accepts UTF-16 with BOM (LE or BE)
    - Rejects binary null bytes in UTF-8
    """
    file.seek(0)
    content = file.read()
    file.seek(0)

    # 1. Try UTF-16 with BOM
    if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
        try:
            content.decode("utf-16")
            return
        except UnicodeDecodeError as exc:
            raise ValidationError(_("Invalid UTF-16 text encoding.")) from exc

    # 2. Try UTF-8 (rejecting null bytes which indicate binary data)
    if b"\x00" in content:
        raise ValidationError(_("Plain text file contains binary null characters."))

    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            _("Plain text file must be valid UTF-8 (with or without BOM) or UTF-16 with BOM.")
        ) from exc

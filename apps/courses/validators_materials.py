import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.assignments.validators import (
    _validate_image_content,
    _validate_office_archive,
    _validate_pdf_content,
    _validate_text_content,
    sanitize_display_filename,
    validate_filename_extensions,
)

VIEW_ONLY_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def material_file_path(instance, filename: str) -> str:
    """
    Generates a secure, collision-resistant storage path for material files:
    materials/course_<id>/<uuid4>_<sanitized_name>
    """
    clean_name = sanitize_display_filename(filename)
    unique_id = uuid.uuid4().hex
    course_id = (
        instance.material.course_id
        if hasattr(instance, "material") and instance.material
        else "general"
    )
    return f"materials/course_{course_id}/{unique_id}_{clean_name}"


def validate_material_file(file) -> None:
    """
    Strict server-side validation for uploaded material files.
    - Size cap: settings.MATERIAL_MAX_FILE_SIZE_BYTES (default 25 MB)
    - Extension allowlist and dangerous intermediate extension checks
    - Executable binary signature rejection (MZ / ELF)
    - Magic bytes and structural verification (PDF, Office XML, Pillow image verification, UTF text)
    """
    if not file:
        return

    # 1. Size Check using MATERIAL_MAX_FILE_SIZE_BYTES
    max_size = getattr(settings, "MATERIAL_MAX_FILE_SIZE_BYTES", 25 * 1024 * 1024)
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
    elif final_ext in ("docx", "pptx"):
        _validate_office_archive(file, final_ext, header)
    elif final_ext == "txt":
        _validate_text_content(file)

    # Always restore file read pointer
    file.seek(0)

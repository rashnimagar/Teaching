import uuid

from apps.assignments.validators import (
    sanitize_display_filename,
    validate_submission_file,
)

VIEW_ONLY_ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


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


def validate_material_file(file_obj) -> None:
    """
    Strict server-side validation for uploaded material files.
    Reuses the robust validation suite:
    - Size cap (settings.ASSIGNMENT_MAX_FILE_SIZE_BYTES)
    - Extension allowlist and dangerous intermediate extension checks
    - Executable binary signature rejection (MZ / ELF)
    - Magic bytes and structural verification (PDF, Office XML, Pillow image verification, UTF text)
    """
    validate_submission_file(file_obj)

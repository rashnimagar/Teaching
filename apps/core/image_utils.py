import io
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image


def generate_webp_variant(image_field, max_width=1200, max_height=800, quality=85):
    """
    Generate a resized, optimized WebP variant from an ImageField.
    Returns (filename, ContentFile) or (None, None).
    """
    if not image_field:
        return None, None

    try:
        if hasattr(image_field, "seek"):
            image_field.seek(0)
        with Image.open(image_field) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                converted = img.convert("RGBA")
            else:
                converted = img.convert("RGB")

            converted.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            converted.save(buffer, format="WEBP", quality=quality, optimize=True)
            buffer.seek(0)

            base_name = Path(image_field.name).stem
            webp_name = f"{base_name}.webp"
            return webp_name, ContentFile(buffer.getvalue())
    except Exception:
        return None, None

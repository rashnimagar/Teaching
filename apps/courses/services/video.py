import hashlib
import re
import time

from django.conf import settings

from apps.courses.models import Lesson

YOUTUBE_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
VIMEO_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{5,20}$")
VIMEO_HASH_RE = re.compile(r"^[0-9a-zA-Z_-]{6,64}$")
BUNNY_ID_RE = re.compile(r"^[0-9a-fA-F-]{10,64}$")


def generate_bunny_token(
    library_id: str, video_id: str, token_key: str, expires_in: int = 3600
) -> tuple[str, int]:
    """
    Computes a signed token for Bunny Stream embedded view authentication.
    Formula per Bunny Stream documentation:
      token = sha256(token_security_key + video_id + str(expires_timestamp_in_seconds)).hexdigest()
    Returns (token_hex, expires_timestamp).
    """
    expires = int(time.time()) + expires_in
    hash_str = f"{token_key}{video_id}{expires}"
    token = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()
    return token, expires


def build_safe_video_embed_url(
    provider: str,
    video_id: str,
    video_hash: str = "",
) -> str:
    """
    Constructs a validated, safe embed URL for supported video providers.
    Returns empty string if video_id is blank.
    Raises ValueError for unsupported providers or malformed identifiers.
    """
    if not video_id or not video_id.strip():
        return ""

    vid = video_id.strip()
    p = (provider or "").lower().strip()

    if p == Lesson.VideoProvider.YOUTUBE or p == "youtube":
        if not YOUTUBE_RE.match(vid):
            raise ValueError(f"Invalid YouTube video ID format: {vid}")
        return f"https://www.youtube-nocookie.com/embed/{vid}?rel=0"

    elif p == Lesson.VideoProvider.VIMEO or p == "vimeo":
        if not VIMEO_ID_RE.match(vid):
            raise ValueError(f"Invalid Vimeo video ID format: {vid}")
        url = f"https://player.vimeo.com/video/{vid}?dnt=1"
        if video_hash and video_hash.strip():
            vhash = video_hash.strip()
            if not VIMEO_HASH_RE.match(vhash):
                raise ValueError(f"Invalid Vimeo video hash format: {vhash}")
            url = f"https://player.vimeo.com/video/{vid}?h={vhash}&dnt=1"
        return url

    elif p == Lesson.VideoProvider.BUNNY or p == "bunny":
        if not BUNNY_ID_RE.match(vid):
            raise ValueError(f"Invalid Bunny Stream video ID format: {vid}")
        library_id = getattr(settings, "BUNNY_STREAM_LIBRARY_ID", "") or "default"
        base_url = f"https://iframe.mediadelivery.net/embed/{library_id}/{vid}"

        signing_enabled = getattr(settings, "BUNNY_STREAM_SIGNING_ENABLED", False)
        token_key = getattr(settings, "BUNNY_STREAM_TOKEN_KEY", "")
        if signing_enabled and token_key and library_id:
            token, expires = generate_bunny_token(library_id, vid, token_key)
            return f"{base_url}?token={token}&expires={expires}"
        return base_url

    else:
        raise ValueError(f"Unsupported video provider: {provider}")


def extract_video_info(raw_input: str, current_provider: str = "") -> dict[str, str]:
    """
    Extracts clean video ID, optional provider, and optional video hash from raw input or full URLs.
    Handles YouTube, Vimeo, and Bunny Stream URLs.
    """
    if not raw_input or not raw_input.strip():
        return {"video_id": "", "provider": current_provider or "", "video_hash": ""}

    text = raw_input.strip()

    # 1. YouTube
    yt_match = re.search(
        r"(?:youtube(?:-nocookie)?\.com\/(?:watch\?.*v=|embed\/|v\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
        text,
    )
    if yt_match:
        return {
            "video_id": yt_match.group(1),
            "provider": Lesson.VideoProvider.YOUTUBE,
            "video_hash": "",
        }

    # 2. Vimeo with path hash (e.g. vimeo.com/76979871/d7a12b45e8)
    vimeo_hash_match = re.search(
        r"vimeo\.com\/(?:video\/)?([0-9a-zA-Z_-]{5,20})\/([0-9a-zA-Z_-]{6,64})",
        text,
    )
    if vimeo_hash_match:
        return {
            "video_id": vimeo_hash_match.group(1),
            "provider": Lesson.VideoProvider.VIMEO,
            "video_hash": vimeo_hash_match.group(2),
        }

    # 2b. Vimeo with query parameter hash (e.g. vimeo.com/76979871?h=d7a12b45e8)
    vimeo_param_match = re.search(
        r"vimeo\.com\/(?:video\/)?([0-9a-zA-Z_-]{5,20}).*[\?&]h=([0-9a-zA-Z_-]{6,64})",
        text,
    )
    if vimeo_param_match:
        return {
            "video_id": vimeo_param_match.group(1),
            "provider": Lesson.VideoProvider.VIMEO,
            "video_hash": vimeo_param_match.group(2),
        }

    # 2c. Simple Vimeo URL (e.g. vimeo.com/76979871)
    vimeo_simple_match = re.search(
        r"vimeo\.com\/(?:video\/)?([0-9a-zA-Z_-]{5,20})",
        text,
    )
    if vimeo_simple_match:
        return {
            "video_id": vimeo_simple_match.group(1),
            "provider": Lesson.VideoProvider.VIMEO,
            "video_hash": "",
        }

    # 3. Bunny Stream URL (e.g. iframe.mediadelivery.net/embed/12345/GUID or video.bunnycdn.com/play/12345/GUID)
    bunny_match = re.search(
        r"(?:mediadelivery\.net\/embed|video\.bunnycdn\.com\/play)\/[^\/]+\/([0-9a-fA-F-]{10,64})",
        text,
    )
    if bunny_match:
        return {
            "video_id": bunny_match.group(1),
            "provider": Lesson.VideoProvider.BUNNY,
            "video_hash": "",
        }

    return {
        "video_id": text,
        "provider": current_provider or "",
        "video_hash": "",
    }

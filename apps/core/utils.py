from django.conf import settings


def get_client_ip(group, request) -> str:
    """
    Extract the real client IP address from the request headers,
    accounting for reverse proxies via RATELIMIT_IP_META_KEY.
    """
    meta_key = getattr(settings, "RATELIMIT_IP_META_KEY", "REMOTE_ADDR")
    raw_ip = request.META.get(meta_key, request.META.get("REMOTE_ADDR", ""))
    if raw_ip and "," in raw_ip:
        # If multiple IPs are forwarded, the first is the client's original IP
        raw_ip = raw_ip.split(",")[0].strip()
    return raw_ip or "127.0.0.1"


def serialize_json_ld(data: dict) -> str:
    """
    Safely serialize dictionary to JSON-LD string escaping HTML/script tags
    to prevent XSS or tag breakout when rendered inside <script type="application/ld+json">.
    """
    import json

    raw_json = json.dumps(data, ensure_ascii=False)
    return raw_json.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")

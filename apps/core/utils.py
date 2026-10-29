import ipaddress
import json

from django.conf import settings
from django.http.request import split_domain_port


def parse_valid_ip(raw_ip: str | None) -> str | None:
    """
    Validate and normalize an IPv4 or IPv6 address (stripping optional ports or brackets).
    Returns None if the entry is empty or malformed.
    """
    if not raw_ip or not isinstance(raw_ip, str):
        return None
    candidate = raw_ip.strip()
    if not candidate:
        return None

    try:
        domain, port = split_domain_port(candidate)
        if port and domain:
            candidate = domain
            if candidate.startswith("[") and candidate.endswith("]"):
                candidate = candidate[1:-1]
        elif candidate.startswith("[") and candidate.endswith("]"):
            candidate = candidate[1:-1]
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def get_client_ip(group, request) -> str:
    """
    Extract the real client IP address from the request safely:
    1. If ALLAUTH_TRUSTED_CLIENT_IP_HEADER (or TRUSTED_CLIENT_IP_HEADER) is configured,
       extract and validate the IP from that header; fall back to REMOTE_ADDR if missing/malformed.
    2. Otherwise, check NUM_PROXIES (or ALLAUTH_TRUSTED_PROXY_COUNT):
       - When 0 (default): ignore X-Forwarded-For completely and use REMOTE_ADDR.
       - When N > 0: split X-Forwarded-For by comma; if fewer than N entries exist,
         or the target hop `entries[-N]` is malformed, fall back safely to REMOTE_ADDR.
    """
    remote_addr = parse_valid_ip(request.META.get("REMOTE_ADDR", "")) or "127.0.0.1"

    trusted_header = getattr(settings, "ALLAUTH_TRUSTED_CLIENT_IP_HEADER", None) or getattr(
        settings, "TRUSTED_CLIENT_IP_HEADER", None
    )
    if trusted_header:
        header_val = None
        if hasattr(request, "headers"):
            header_val = request.headers.get(trusted_header)
        if not header_val:
            meta_name = "HTTP_" + trusted_header.upper().replace("-", "_")
            header_val = request.META.get(meta_name)
        parsed = parse_valid_ip(header_val)
        if parsed:
            return parsed
        return remote_addr

    num_proxies = getattr(settings, "NUM_PROXIES", None)
    if num_proxies is None:
        num_proxies = getattr(settings, "ALLAUTH_TRUSTED_PROXY_COUNT", 0)

    try:
        num_proxies = int(num_proxies)
    except (TypeError, ValueError):
        num_proxies = 0

    if num_proxies <= 0:
        return remote_addr

    xff = None
    if hasattr(request, "headers"):
        xff = request.headers.get("X-Forwarded-For")
    if not xff:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if not xff:
        return remote_addr

    hops = [hop.strip() for hop in xff.split(",") if hop.strip()]
    if len(hops) < num_proxies:
        return remote_addr

    target_hop = hops[-num_proxies]
    parsed_hop = parse_valid_ip(target_hop)
    if parsed_hop is None:
        return remote_addr

    return parsed_hop


def serialize_json_ld(data: dict) -> str:
    """
    Safely serialize dictionary to JSON-LD string escaping HTML/script tags
    to prevent XSS or tag breakout when rendered inside <script type="application/ld+json">.
    """
    raw_json = json.dumps(data, ensure_ascii=False)
    return raw_json.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")

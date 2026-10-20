import re
import unicodedata
from urllib.parse import urlencode

from django import template

register = template.Library()

# Regex pattern matching a complete Devanagari grapheme cluster / syllable:
# Base consonant or independent vowel + optional nukta + zero or more (virama + optional ZWJ/ZWNJ + consonant + optional nukta) + optional vowel sign (matra) + optional anusvara/visarga/candrabindu.
DEV_GRAPHEME_PATTERN = re.compile(
    r"^([\u0904-\u0939\u0958-\u0961\u0972-\u097F][\u093c]?"
    r"(?:\u094d[\u200c\u200d]?[\u0915-\u0939\u0958-\u095f][\u093c]?)*"
    r"(?:[\u093e-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963])?"
    r"[\u0901-\u0903]?)"
)


@register.filter(name="initial_grapheme")
def initial_grapheme(value):
    """
    Extracts the first whole grapheme / syllable from a string or user object.
    Preserves complete Devanagari conjuncts and vowel signs (e.g. 'राम' -> 'रा',
    'क्षत्रिय' -> 'क्ष', 'ज्ञान' -> 'ज्ञा', 'प्रदीप' -> 'प्र') and Latin letters ('Python' -> 'P').
    Returns an empty string if no valid letter/digit is found, allowing the template to fall back to an icon.
    """
    if value is None:
        return ""

    # If a User model or similar object is passed, extract best available display name
    if hasattr(value, "get_full_name"):
        full_name = value.get_full_name().strip()
        first_name = getattr(value, "first_name", "").strip()
        email = getattr(value, "email", "").strip()
        text = full_name or first_name or email
    else:
        text = str(value)

    # Normalize unicode to Canonical Composition
    text = unicodedata.normalize("NFC", text).strip()
    if not text:
        return ""

    # 1. Check for Devanagari syllable / conjunct
    dev_match = DEV_GRAPHEME_PATTERN.match(text)
    if dev_match:
        return dev_match.group(1)

    # 2. Check for standard alphanumeric character (Latin, accented, digits)
    first_char = text[0]
    if first_char.isalnum():
        return first_char.upper()

    # Fall back to empty string so template renders a default SVG icon
    return ""


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Preserves existing GET query parameters while replacing or adding new ones.
    Useful for pagination and filter links that must preserve search terms.

    Example:
        <a href="?{% url_replace page=page_obj.next_page_number %}">Next</a>
    """
    request = context.get("request")
    if not request or not hasattr(request, "GET"):
        clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return urlencode(clean_kwargs)

    query = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == "":
            query.pop(key, None)
        else:
            query[key] = str(value)

    return query.urlencode()

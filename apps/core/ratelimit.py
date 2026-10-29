"""
Project rate-limiting wrapper that attaches `ratelimit_spec` metadata directly
onto the decorated view (and CBV view class) so the URL access matrix and
endpoint inventory tests can verify rate limits deterministically.
"""

from __future__ import annotations

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit as django_ratelimit


def _format_key_name(key) -> str:
    if isinstance(key, str):
        return key
    if callable(key):
        return getattr(key, "__name__", str(key))
    return str(key)


def track_ratelimit(*, key, rate: str, block: bool = True, method=None, group: str | None = None):
    """
    Wraps django_ratelimit.decorators.ratelimit and records the specification
    on `view.ratelimit_spec` (as a list of dicts, outermost/first-applied preserved)
    for automated security audit verification.
    """
    rl_kwargs = {"key": key, "rate": rate, "block": block}
    if method is not None:
        rl_kwargs["method"] = method
    if group is not None:
        rl_kwargs["group"] = group

    spec_entry = {
        "key": _format_key_name(key),
        "rate": rate,
        "block": block,
        "method": tuple(method) if isinstance(method, (list, tuple)) else (method or "ALL"),
    }

    inner_decorator = django_ratelimit(**rl_kwargs)

    def _decorator(target):
        # Support decorating a class-based view directly (decorates dispatch)
        if isinstance(target, type):
            existing = list(getattr(target, "ratelimit_spec", []))
            existing.append(spec_entry)
            decorated_cls = method_decorator(inner_decorator, name="dispatch")(target)
            decorated_cls.ratelimit_spec = existing
            return decorated_cls

        existing = list(getattr(target, "ratelimit_spec", []))
        existing.append(spec_entry)
        wrapped = inner_decorator(target)
        wrapped.ratelimit_spec = existing
        return wrapped

    return _decorator


def get_view_ratelimit_specs(view_func) -> list[dict]:
    """
    Retrieve recorded ratelimit_spec list from a function-based view or CBV `.as_view()` callback.
    """
    curr = view_func
    visited = set()
    while curr and id(curr) not in visited:
        visited.add(id(curr))
        specs = getattr(curr, "ratelimit_spec", None)
        if specs:
            return list(specs)
        view_cls = getattr(curr, "view_class", None)
        if view_cls:
            cls_specs = getattr(view_cls, "ratelimit_spec", None)
            if cls_specs:
                return list(cls_specs)
        curr = getattr(curr, "__wrapped__", None)
    return []

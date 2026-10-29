from django.conf import settings
from django.core.checks import Error, Tags, register

UNSAFE_PROD_CACHE_BACKENDS = {
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
}


@register(Tags.caches, Tags.security, deploy=True)
def check_production_shared_cache(app_configs, **kwargs):
    """
    core.E001: Deployment check ensuring the default cache backend is not a per-process
    LocMemCache or DummyCache in production, because rate limits and cross-worker
    cache invalidations require a shared cache (Redis or DatabaseCache).
    """
    errors = []
    caches = getattr(settings, "CACHES", {})
    default_cache = caches.get("default", {})
    backend = default_cache.get("BACKEND", "")

    if backend in UNSAFE_PROD_CACHE_BACKENDS or "LocMemCache" in backend or "DummyCache" in backend:
        errors.append(
            Error(
                f"Default cache backend '{backend}' is per-process or a no-op and cannot enforce "
                "rate limits across multiple Gunicorn/ASGI workers in production.",
                hint=(
                    "Configure CACHE_URL in production to use a shared cache backend such as "
                    "Redis (e.g. CACHE_URL=redis://127.0.0.1:6379/1) or Django's DatabaseCache "
                    "(e.g. CACHE_URL=dbcache://django_cache_table)."
                ),
                id="core.E001",
            )
        )
    return errors

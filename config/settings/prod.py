from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

# Fail-fast validation for SECRET_KEY
prod_secret_key = env("SECRET_KEY", default=None)
if (
    not prod_secret_key
    or prod_secret_key == "django-insecure-development-placeholder-key"
    or "insecure" in prod_secret_key
):
    raise ImproperlyConfigured(
        "CRITICAL: A secure, unique SECRET_KEY environment variable is required in production."
    )
SECRET_KEY = prod_secret_key

# Fail-fast validation for ALLOWED_HOSTS
prod_allowed_hosts = env.list("ALLOWED_HOSTS", default=[])
if not prod_allowed_hosts or prod_allowed_hosts == ["*"]:
    raise ImproperlyConfigured(
        "CRITICAL: ALLOWED_HOSTS must be explicitly defined and non-empty in production."
    )
ALLOWED_HOSTS = prod_allowed_hosts

# Production Database via DATABASE_URL
database_url = env("DATABASE_URL", default=None)
if not database_url:
    raise ImproperlyConfigured("CRITICAL: DATABASE_URL must be configured in production.")
DATABASES = {"default": env.db("DATABASE_URL")}

# WhiteNoise Compressed & Manifest Static Storage for production
STORAGES["staticfiles"] = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# Production SSL & Hardened Security Headers
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Production Shared Cache (Redis or DB Cache via CACHE_URL)
CACHES = {
    "default": env.cache(
        "CACHE_URL",
        default="locmemcache://",
    )
}

# Production Email (SMTP)
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Teaching Platform <noreply@example.com>")

# Sentry Error Monitoring
sentry_dsn = env("SENTRY_DSN", default=None)
if sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,
    )

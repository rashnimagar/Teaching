from .base import *

DEBUG = True

# SQLite database for local development
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

# Console Email Backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Django Debug Toolbar
INSTALLED_APPS += ["debug_toolbar"]

# Insert DebugToolbarMiddleware right after WhiteNoiseMiddleware
if "whitenoise.middleware.WhiteNoiseMiddleware" in MIDDLEWARE:
    index = MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware") + 1
    MIDDLEWARE.insert(index, "debug_toolbar.middleware.DebugToolbarMiddleware")
else:
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

INTERNAL_IPS = ["127.0.0.1", "::1"]

# Cache: In-memory local cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "teaching-dev-cache",
    }
}

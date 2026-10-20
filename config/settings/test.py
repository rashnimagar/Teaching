from .base import *

DEBUG = False

# Fast in-memory SQLite for tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Speed up test password hashing
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# In-memory email backend for testing
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# In-memory cache for testing
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "teaching-test-cache",
    }
}

# Ensure plain StaticFilesStorage in tests
STORAGES["staticfiles"] = {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

# Isolate external OAuth provider credentials in test environment
GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
SOCIALACCOUNT_PROVIDERS["google"]["APPS"] = []

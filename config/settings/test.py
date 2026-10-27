from .base import *

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

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


# Guard against silent template typos in tests
class InvalidVarSentinel(str):
    def __mod__(self, missing):
        raise AttributeError(f"Unresolved template variable: {missing!r}")


TEMPLATES[0]["OPTIONS"]["string_if_invalid"] = InvalidVarSentinel("%s")

# Enable error preview routes in test environment via test URLconf
ENABLE_TEST_ERROR_ROUTES = True
ROOT_URLCONF = "config.urls_test"

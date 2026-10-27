from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Initialize environment parser
env = environ.Env()

# Read .env file if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

# Secret key & debug defaults
SECRET_KEY = env("SECRET_KEY", default="django-insecure-development-placeholder-key")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

# Application definition
INSTALLED_APPS = [
    # Django core apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    # Third-party apps
    "django_tailwind_cli",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    # Project apps
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.courses.apps.CoursesConfig",
    "apps.assignments.apps.AssignmentsConfig",
    "apps.dashboard.apps.DashboardConfig",
    "apps.notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Right after SecurityMiddleware
    "csp.middleware.CSPMiddleware",  # django-csp (processes CSP and reports)
    "apps.core.middleware.SecurityHeadersMiddleware",  # Permissions-Policy, CORP, COOP
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.SessionIdleTimeoutMiddleware",  # Idle session expiration
    "allauth.account.middleware.AccountMiddleware",  # Required by django-allauth
    "apps.core.middleware.RatelimitMiddleware",  # Intercepts 429 Ratelimited
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site_settings",
                "apps.notifications.context_processors.notifications_context",
                "apps.dashboard.context_processors.teacher_nav_context",
            ],
        },
    },
]

SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    # Default backend for Django admin superuser login
    "django.contrib.auth.backends.ModelBackend",
    # Allauth authentication backend for social login
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Authentication & Redirect URLs
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "dashboard:student"
ACCOUNT_LOGOUT_REDIRECT_URL = "core:home"

# Allauth Account Settings
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = False
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_ADAPTER = "apps.accounts.adapters.CustomAccountAdapter"
ACCOUNT_FORMS = {
    "login": "apps.accounts.forms.CustomLoginForm",
    "signup": "apps.accounts.forms.CustomSignupForm",
}
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "organization_code"

# Allauth Rate Limits
ACCOUNT_RATE_LIMITS = {
    "login": "60/m/ip",
    "login_failed": "10/m/ip,5/300s/key",
    "signup": "20/m/ip",
    "reset_password": "20/m/ip,5/m/key",
    "reset_password_from_key": "20/m/ip",
    "confirm_email": "10/m/ip,3/180s/key",
}

# Allauth Social Account Settings
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.CustomSocialAccountAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Google OAuth Provider Settings
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "VERIFIED_EMAIL": True,
        "APPS": [
            {
                "client_id": GOOGLE_CLIENT_ID,
                "secret": GOOGLE_CLIENT_SECRET,
                "key": "",
            }
        ]
        if GOOGLE_CLIENT_ID
        else [],
    }
}

# Rate Limiting Configuration
RATELIMIT_IP_META_KEY = env("RATELIMIT_IP_META_KEY", default="REMOTE_ADDR")

# Password validation: min 10 chars, no composition rules, allows long passphrases
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 10,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
]

# Default Sending Email Address
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Teaching Platform <noreply@example.com>")
NOTIFY_BY_EMAIL = env.bool("NOTIFY_BY_EMAIL", default=False)

# Internationalization & Localization
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="Asia/Kathmandu")
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Swappable Storages
STORAGES = {
    "default": {
        "BACKEND": env(
            "MEDIA_STORAGE_BACKEND", default="django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
    "private": {
        "BACKEND": env(
            "PRIVATE_STORAGE_BACKEND", default="django.core.files.storage.FileSystemStorage"
        ),
        "OPTIONS": {
            "location": str(BASE_DIR / "private_media"),
            "base_url": None,
        },
    },
}

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Assignment Submissions Configuration
ASSIGNMENT_MAX_FILE_SIZE_BYTES = env.int(
    "ASSIGNMENT_MAX_FILE_SIZE_BYTES", default=10 * 1024 * 1024
)  # 10 MB
ASSIGNMENT_MAX_TEXT_LENGTH = env.int("ASSIGNMENT_MAX_TEXT_LENGTH", default=20000)
ASSIGNMENT_MAX_IMAGE_PIXELS = env.int("ASSIGNMENT_MAX_IMAGE_PIXELS", default=25_000_000)
ASSIGNMENT_MAX_IMAGE_DIMENSION = env.int("ASSIGNMENT_MAX_IMAGE_DIMENSION", default=10000)
ASSIGNMENT_ZIP_MAX_ENTRIES = env.int("ASSIGNMENT_ZIP_MAX_ENTRIES", default=1000)
ASSIGNMENT_ZIP_MAX_UNCOMPRESSED_BYTES = env.int(
    "ASSIGNMENT_ZIP_MAX_UNCOMPRESSED_BYTES", default=50 * 1024 * 1024
)

# Material Files Configuration
MATERIAL_MAX_FILE_SIZE_BYTES = env.int(
    "MATERIAL_MAX_FILE_SIZE_BYTES", default=25 * 1024 * 1024
)  # 25 MB

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tailwind CLI Configuration
TAILWIND_CLI_SRC_CSS = "static/css/input.css"
TAILWIND_CLI_DIST_CSS = "css/dist/tailwind.css"
# SILENCED_SYSTEM_CHECKS is consolidated below

# Cache Configuration
CACHES = {
    "default": env.cache(
        "CACHE_URL",
        default="locmemcache://",
    )
}

# Structured Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} [{name}:{lineno}] {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# Video Provider Configuration (Bunny Stream)
BUNNY_STREAM_LIBRARY_ID = env("BUNNY_STREAM_LIBRARY_ID", default="")
BUNNY_STREAM_TOKEN_KEY = env("BUNNY_STREAM_TOKEN_KEY", default="")
BUNNY_STREAM_SIGNING_ENABLED = env.bool("BUNNY_STREAM_SIGNING_ENABLED", default=False)

# Custom CSRF Failure View & Trusted Origins
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Session Idle Timeout (Inactivity timeout in seconds; 0 = disabled by default)
SESSION_IDLE_TIMEOUT_SECONDS = env.int("SESSION_IDLE_TIMEOUT_SECONDS", default=0)

# Deliberately silence security.W021 during initial HSTS ramp-up (documented in SECURITY.md)
# and django_tailwind_cli.W001 (Tailwind input CSS inside static directory)
SILENCED_SYSTEM_CHECKS = [
    "django_tailwind_cli.W001",
    "security.W021",
]

# Django 6.0 transitional setting: Default URLField scheme in forms to https
FORMS_URLFIELD_ASSUME_HTTPS = True

# Admin URL configuration (customizable via env, used for routing and CSP exclusion)
DJANGO_ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")
ADMIN_URL_PREFIX = f"/{DJANGO_ADMIN_URL.strip('/')}/"

# Content Security Policy (django-csp 4.0 configuration)
CSP_DIRECTIVES = {
    "default-src": ["'self'"],
    "script-src": ["'self'"],
    "style-src": ["'self'"],
    "img-src": ["'self'", "data:", "https://i.ytimg.com"],
    "font-src": ["'self'"],
    "connect-src": ["'self'"],
    "frame-src": [
        "https://www.youtube-nocookie.com",
        "https://player.vimeo.com",
        "https://iframe.mediadelivery.net",
    ],
    "frame-ancestors": ["'none'"],
    "form-action": ["'self'", "https://accounts.google.com"],
    "base-uri": ["'self'"],
    "object-src": ["'none'"],
}

# Enforce Content Security Policy site-wide (excluding admin using DJANGO_ADMIN_URL prefix)
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": CSP_DIRECTIVES,
    "EXCLUDE_URL_PREFIXES": [ADMIN_URL_PREFIX],
}
CONTENT_SECURITY_POLICY_REPORT_ONLY = None

# Flag controlling registration of direct error preview routes (/403/, /404/, /500/)
ENABLE_TEST_ERROR_ROUTES = False

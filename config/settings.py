"""
Django settings for the Commissioner (Appeals-II), Inland Revenue
appeals management system. Building Regional Tax Office, Faisalabad.

DEBUG defaults to OFF. To run in development mode, set the environment
variable CIR_DEBUG=1 before starting the server.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Secret key
# ---------------------------------------------------------------------------
def _get_secret_key():
    """Read the key from the environment, else from a local file.

    The file is created with a fresh random key on first run and is excluded
    from git, so the key never lives in source control and stays stable across
    restarts (a changing key would sign every user out).
    """
    env_key = os.environ.get("CIR_SECRET_KEY")
    if env_key:
        return env_key

    key_file = BASE_DIR / "secret_key.txt"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    new_key = secrets.token_urlsafe(64)
    key_file.write_text(new_key, encoding="utf-8")
    return new_key


SECRET_KEY = _get_secret_key()

DEBUG = os.environ.get("CIR_DEBUG", "").strip() in {"1", "true", "True", "yes"}

# Hosts this system may be reached on. Add the server's address here when the
# system moves to the office data server.
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "10.10.14.230",     # host PC, office LAN
    "192.168.137.1",    # host PC, mobile hotspot
    "10.10.12.99",      # office data server (planned)
]

# Extra hosts can be added at run time without editing this file:
#   set CIR_ALLOWED_HOSTS=10.10.14.55,10.10.14.60
_extra_hosts = os.environ.get("CIR_ALLOWED_HOSTS", "")
if _extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in _extra_hosts.split(",") if h.strip()]

# Form posts are same-origin, but Django checks the Origin header explicitly.
CSRF_TRUSTED_ORIGINS = [
    f"http://{host}:8020" for host in ALLOWED_HOSTS if host != "localhost"
] + [f"http://{host}" for host in ALLOWED_HOSTS if host != "localhost"]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "appeals",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves static files with DEBUG off, so no separate web server is needed.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.office_info",
                "core.context_processors.user_counts",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # Allows readers while a write is in progress - fewer
            # "database is locked" errors when several clerks work at once.
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "timeout": 20,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static and media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # Compresses files and adds a content hash to each name, so browsers
        # cache aggressively but always pick up a changed file immediately.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Authentication and sessions
# ---------------------------------------------------------------------------
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_AGE = 8 * 60 * 60          # one working day
SESSION_SAVE_EVERY_REQUEST = True          # idle timeout, not a fixed 8 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# The system runs over plain HTTP on a closed office LAN, so the HTTPS-only
# options stay off. Turn them on if a certificate is ever installed.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False               # the forms post the token normally
SESSION_COOKIE_SECURE = False              # no HTTPS on the LAN
CSRF_COOKIE_SECURE = False

# Friendly page instead of Django's bare "Forbidden (403)" when a form is
# submitted with a stale token - which happens to everyone once after the
# SECRET_KEY changes, and to anyone who leaves a form open too long.
CSRF_FAILURE_VIEW = "core.views.csrf_failure"


# ---------------------------------------------------------------------------
# Logging - errors go to a file, since there is no console window to watch
# ---------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "errors.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["file"],
            "level": "WARNING",
            "propagate": True,
        },
    },
}


# ---------------------------------------------------------------------------
# Office identity (surfaced in templates via core.context_processors)
# ---------------------------------------------------------------------------
OFFICE_NAME = "Commissioner (Appeals-II), Inland Revenue"
OFFICE_SUBTITLE = "Building Regional Tax Office, Faisalabad"
OFFICE_SHORT = "Commissioner (Appeals-II)"

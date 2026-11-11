"""Gold Volt settings. Secrets and paths come from a protected config file."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("GOLDVOLT_CONFIG", BASE_DIR / ".dev" / "config.json"))
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

SECRET_KEY = CONFIG["secret_key"]
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "accounts",
    "audit",
    "parties",
    "catalog",
    "ledger",
    "inventory",
    "reports",
    "system",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.SessionGuardMiddleware",
    "accounts.middleware.DenyByDefaultMiddleware",
    "audit.middleware.PageOpenMiddleware",
]

ROOT_URLCONF = "goldvolt.urls"
WSGI_APPLICATION = "goldvolt.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context.role",
            ],
        },
    },
]

# Day-to-day the service connects as goldvolt_app. Only the installer, updates
# and the test harness set GOLDVOLT_DB_ROLE=owner.
_owner = os.environ.get("GOLDVOLT_DB_ROLE") == "owner"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": CONFIG["db_name"],
        "USER": "goldvolt_owner" if _owner else "goldvolt_app",
        "PASSWORD": CONFIG["owner_password" if _owner else "app_password"],
        "HOST": CONFIG["db_host"],
        "PORT": CONFIG["db_port"],
        "TEST": {"NAME": "test_goldvolt"},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
LOGIN_URL = "login"

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_NAME = "gv_session"
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_NAME = "gv_csrf"
LANGUAGE_COOKIE_SAMESITE = "Strict"
LANGUAGE_COOKIE_NAME = "gv_lang"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'"],
        "img-src": ["'self'"],
        "font-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'none'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
}

LANGUAGE_CODE = "ar"
LANGUAGES = [("ar", "العربية"), ("fr", "Français")]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
USE_THOUSAND_SEPARATOR = False
USE_TZ = True
TIME_ZONE = "Africa/Algiers"

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False

MEDIA_ROOT = CONFIG["media_root"]

_log_dir = Path(CONFIG["log_dir"])
_log_dir.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(_log_dir / "goldvolt.log"),
            "when": "midnight",
            "backupCount": 30,
            "encoding": "utf-8",
            "delay": True,
            "formatter": "plain",
        },
    },
    "root": {"handlers": ["file"], "level": "WARNING"},
}

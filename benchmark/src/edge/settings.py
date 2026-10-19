import os
import sys

from edge.config import postgres_database, setting

SECRET_KEY = setting("DJANGO_SECRET_KEY", "local-checks-only-not-a-deployment-key")
DEBUG = False
ALLOWED_HOSTS = ["*"]
ROOT_URLCONF = "edge.urls"
INSTALLED_APPS = ["pgtrigger", "django.contrib.auth", "django.contrib.contenttypes", "demo"]
MIDDLEWARE = [
    "edge.middleware.MeasurementMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
AUTH_USER_MODEL = "demo.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
PASSWORD_HASHERS = ["edge.hashers.BenchmarkPasswordHasher"]
SESSION_ENGINE = "edge.sessions"
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_SECURE = not bool(setting("EDGE_LOCAL"))
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASE_ROUTERS = ["edge.routing.CacheRouter"]
MIRRORED_MODELS = ["demo.User", "demo.Session", "demo.Post"]
if os.environ.get("EDGE_SQLITE_TEST"):
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
        "cache": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
        "cache_maintenance": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    }
else:
    # The D1 adapter imports the Worker runtime. Native management/trigger tests
    # use only PostgreSQL; D1 migrations and operations run inside workerd.
    cache_engine = (
        "edge.backends.d1" if sys.platform == "emscripten" else "django.db.backends.dummy"
    )
    DATABASES = {
        "default": postgres_database(),
        "cache": {"ENGINE": cache_engine, "CLOUDFLARE_BINDING": "CACHE"},
        "cache_maintenance": {"ENGINE": cache_engine, "CLOUDFLARE_BINDING": "CACHE"},
    }

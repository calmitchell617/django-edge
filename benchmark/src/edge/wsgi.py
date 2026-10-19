import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edge.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

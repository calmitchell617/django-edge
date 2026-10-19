from django_cf import DjangoCF
from workers import WorkerEntrypoint

from edge.companion import SyncCompanion  # noqa: F401 (exported Durable Object)


class Default(DjangoCF, WorkerEntrypoint):
    def get_app(self):
        # Bindings are available during a request, not during snapshot creation.
        from edge.config import setting

        if not setting("DJANGO_SECRET_KEY"):
            raise RuntimeError("Configure DJANGO_SECRET_KEY before serving requests")
        from edge.wsgi import application

        return application

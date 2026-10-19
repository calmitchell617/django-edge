from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore

from edge.context import state


class SessionStore(DatabaseSessionStore):
    @classmethod
    def get_model_class(cls):
        from demo.models import Session

        return Session

    def save(self, must_create=False):
        # Session creation/cycling/logout always belongs to the authority. The
        # inherited implementation uses router.db_for_write and atomic(default).
        return super().save(must_create=must_create)

    def load(self):
        original_key = self._session_key
        data = super().load()
        current = state.get()
        if original_key and self._session_key is None and current:
            if current.policy in {"auth_cache", "all_cache"}:
                # A replica miss is not evidence that the source session is
                # invalid. Return an anonymous result, retaining the cookie for
                # a later request. No source fallback or implicit session write.
                self._session_key = original_key
        return data

from edge.context import state


class CacheRouter:
    def db_for_read(self, model, **hints):
        current = state.get()
        if current and current.policy in {"auth_cache", "all_cache"}:
            if model._meta.label_lower in {"demo.user", "demo.session"}:
                return "cache"
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "cache":
            return False
        if db == "cache_maintenance":
            return app_label == "demo" and model_name in {"user", "session", "post"}
        return db == "default"

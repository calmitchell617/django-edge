from django.db import models

from edge.context import state


class SyncQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if {"sync_version", "needs_sync"} & kwargs.keys():
            raise ValueError("Replication metadata is database-managed")
        return super(SyncQuerySet, self.using("default")).update(**kwargs)

    def create(self, **kwargs):
        return super(SyncQuerySet, self.using("default")).create(**kwargs)

    def bulk_create(self, *args, **kwargs):
        return super(SyncQuerySet, self.using("default")).bulk_create(*args, **kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if {"sync_version", "needs_sync"} & set(fields):
            raise ValueError("Replication metadata is database-managed")
        return super(SyncQuerySet, self.using("default")).bulk_update(
            objs, fields, batch_size=batch_size
        )

    def get_or_create(self, *args, **kwargs):
        return super(SyncQuerySet, self.using("default")).get_or_create(*args, **kwargs)

    def update_or_create(self, *args, **kwargs):
        return super(SyncQuerySet, self.using("default")).update_or_create(*args, **kwargs)

    def select_for_update(self, *args, **kwargs):
        return super().select_for_update(*args, **kwargs).using("default")

    def eventually_consistent(self):
        current = state.get()
        return self.using("cache" if current and current.policy == "all_cache" else "default")

    def delete(self):
        count = self.using("default").update(is_deleted=True)
        return count, {self.model._meta.label: count}


class LiveManager(models.Manager.from_queryset(SyncQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SyncedModel(models.Model):
    sync_version = models.BigIntegerField(default=1, editable=False)
    needs_sync = models.BooleanField(default=True, editable=False)
    is_deleted = models.BooleanField(default=False, editable=False)
    objects = LiveManager()
    all_objects = models.Manager.from_queryset(SyncQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
        indexes = [
            models.Index(
                fields=["needs_sync"],
                condition=models.Q(needs_sync=True),
                name="%(app_label)s_%(class)s_pending",
            )
        ]

    def delete(self, using=None, keep_parents=False):
        return type(self).all_objects.using("default").filter(pk=self.pk).delete()

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        if update_fields is not None and {"sync_version", "needs_sync"} & set(update_fields):
            raise ValueError("Replication metadata is database-managed")
        if not self._state.adding and update_fields is None:
            # A cached model carries stale replication metadata. Saving it must
            # never acknowledge a pending source change as a side effect.
            update_fields = [
                f.name
                for f in self._meta.concrete_fields
                if not f.primary_key and f.name not in {"sync_version", "needs_sync"}
            ]
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using="default",
            update_fields=update_fields,
        )

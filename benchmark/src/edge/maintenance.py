"""Allowlisted setup operations; never a general SQL/management-command endpoint."""

from io import StringIO

from django.core.management import call_command
from django.db import connections, transaction

from edge.context import request_state
from edge.replication import quote
from edge.sync import mirrored_models


def migrate():
    with request_state(maintenance=True):
        output = StringIO()
        try:
            call_command("migrate", database="default", interactive=False, stdout=output)
            call_command("migrate", database="cache_maintenance", interactive=False, stdout=output)
            return {"migrated": True}
        finally:
            connections.close_all()


def reset(binding):
    from pyodide.ffi import run_sync

    # Called only while the companion's serialization lock is held and disabled.
    models = mirrored_models()
    run_sync(
        binding.batch(
            [binding.prepare(f"DELETE FROM {quote(m._meta.db_table)}") for m in reversed(models)]
        )
    )
    with transaction.atomic(), connections["default"].cursor() as cursor:
        names = ", ".join(quote(m._meta.db_table) for m in models)
        # TRUNCATE is an explicit test reset, not ordinary application deletion.
        cursor.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY")
    connections.close_all()
    return {"reset": True}


def seed(password):
    from django.contrib.auth.hashers import make_password

    from demo.models import Post, User

    if User.all_objects.using("default").exists() or Post.all_objects.using("default").exists():
        raise ValueError("Reset both databases before seeding")
    encoded = make_password(password)
    try:
        with transaction.atomic():
            User.objects.bulk_create(
                [User(username=f"reader{i:03d}", password=encoded) for i in range(100)]
            )
            Post.objects.bulk_create(
                [
                    Post(title=f"Post {i:05d}", content=f"Blog content {i}. " * 30)
                    for i in range(10_000)
                ],
                batch_size=500,
            )
        return {"users": 100, "posts": 10_000}
    finally:
        connections.close_all()

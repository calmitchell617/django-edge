"""Initial fixed-schema reference app; trigger SQL is frozen in 0002."""

from django.db import migrations, models
from django.utils import timezone


def sync_fields():
    return [
        ("sync_version", models.BigIntegerField(default=1, editable=False)),
        ("needs_sync", models.BooleanField(default=True, editable=False)),
        ("is_deleted", models.BooleanField(default=False, editable=False)),
    ]


def options(model):
    return {
        "abstract": False,
        "base_manager_name": "all_objects",
        "indexes": [
            models.Index(
                fields=["needs_sync"],
                condition=models.Q(needs_sync=True),
                name=f"demo_{model}_pending",
            )
        ],
    }


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(blank=True, null=True, verbose_name="last login"),
                ),
                *sync_fields(),
                ("username", models.CharField(max_length=150, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options=options("user"),
            managers=[("objects", models.Manager()), ("all_objects", models.Manager())],
        ),
        migrations.CreateModel(
            name="Session",
            fields=[
                *sync_fields(),
                (
                    "session_key",
                    models.CharField(
                        max_length=40, primary_key=True, serialize=False, verbose_name="session key"
                    ),
                ),
                ("session_data", models.TextField(verbose_name="session data")),
                ("expire_date", models.DateTimeField(db_index=True, verbose_name="expire date")),
            ],
            options=options("session"),
            managers=[("objects", models.Manager()), ("all_objects", models.Manager())],
        ),
        migrations.CreateModel(
            name="Post",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                *sync_fields(),
                ("title", models.CharField(max_length=200)),
                ("content", models.TextField()),
                ("pub_date", models.DateTimeField(default=timezone.now)),
            ],
            options={**options("post"), "ordering": ["-pub_date", "-pk"]},
            managers=[("objects", models.Manager()), ("all_objects", models.Manager())],
        ),
    ]

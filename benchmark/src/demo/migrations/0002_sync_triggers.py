"""Frozen initial pgtrigger operations; subsequent changes use makemigrations."""

import hashlib

from django.db import migrations
from pgtrigger.compiler import Trigger, UpsertTriggerSql
from pgtrigger.migrations import AddTrigger

TRACK_BODY = """
IF TG_OP = 'INSERT' THEN
    NEW.sync_version := 1;
    NEW.needs_sync := TRUE;
ELSIF (to_jsonb(NEW) - 'sync_version' - 'needs_sync')
      IS DISTINCT FROM (to_jsonb(OLD) - 'sync_version' - 'needs_sync') THEN
    NEW.sync_version := OLD.sync_version + 1;
    NEW.needs_sync := TRUE;
ELSE
    NEW.sync_version := OLD.sync_version;
END IF;
RETURN NEW;
"""


def frozen_trigger(model, name, operation, func):
    digest = hashlib.sha1(f"demo.{model}:{name}".encode()).hexdigest()[:5]
    return Trigger(
        name=name,
        sql=UpsertTriggerSql(
            pgid=f"pgtrigger_{name}_{digest}",
            table=f"demo_{model.lower()}",
            when="BEFORE",
            operation=operation,
            func=func,
        ),
    )


class Migration(migrations.Migration):
    dependencies = [("demo", "0001_initial")]
    operations = [
        AddTrigger(model_name=model.lower(), trigger=frozen_trigger(model, name, operation, func))
        for model in ("User", "Session", "Post")
        for name, operation, func in (
            ("track_sync", "INSERT OR UPDATE", TRACK_BODY),
            ("protect_delete", "DELETE", "RAISE EXCEPTION 'Use soft deletion for mirrored rows';"),
        )
    ]

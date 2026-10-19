import pgtrigger

# This compares domain data, not sync metadata. Stale model instances may carry an
# old version: always derive the next version from OLD, never the submitted value.
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


def sync_triggers():
    return [
        pgtrigger.Trigger(
            name="track_sync",
            when=pgtrigger.Before,
            operation=pgtrigger.Insert | pgtrigger.Update,
            func=TRACK_BODY,
        ),
        pgtrigger.Trigger(
            name="protect_delete",
            when=pgtrigger.Before,
            operation=pgtrigger.Delete,
            func="RAISE EXCEPTION 'Use soft deletion for mirrored rows';",
        ),
    ]

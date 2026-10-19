import asyncio
import time

from workers import DurableObject

from edge.replication import next_alarm


def now_ms():
    return int(time.time() * 1000)


class SyncCompanion(DurableObject):
    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self.lock = asyncio.Lock()

    async def control(self, action, payload=None):
        from edge.diagnostics import error_details

        try:
            return await self._control(action, payload)
        except Exception as error:
            # Preserve diagnostics before RPC turns Python errors into JS errors.
            return {"control_error": error_details(error)}

    async def _control(self, action, payload=None):
        from pyodide.ffi import run_sync

        import edge.wsgi  # noqa: F401 (initialize Django within the event)
        from edge import maintenance
        from edge.probe import runtime_probe
        from edge.sync import sync_once

        payload = payload or {}
        async with self.lock:
            status = await self.ctx.storage.get("status") or {
                "enabled": False,
                "failures": 0,
                "interval_ms": 1000,
            }
            if action == "status":
                return {**status, "alarm_ms": await self.ctx.storage.getAlarm()}
            if action == "start":
                status["enabled"] = True
                await self.ctx.storage.put("status", status)
                if not await self.ctx.storage.getAlarm():
                    await self.ctx.storage.setAlarm(now_ms())
            elif action == "stop":
                status["enabled"] = False
                await self.ctx.storage.put("status", status)
                await self.ctx.storage.deleteAlarm()
            elif action == "probe":
                return runtime_probe(self.env.CACHE)
            elif action == "migrate":
                if status["enabled"]:
                    raise ValueError("Stop synchronization before migrating")
                return maintenance.migrate()
            elif action == "reset":
                if status["enabled"]:
                    raise ValueError("Stop synchronization before resetting")
                result = maintenance.reset(self.env.CACHE)
                status = {"enabled": False, "failures": 0, "interval_ms": 1000}
                await self.ctx.storage.put("status", status)
                await self.ctx.storage.deleteAlarm()
                return result
            elif action == "seed":
                if status["enabled"]:
                    raise ValueError("Stop synchronization before seeding")
                return maintenance.seed(payload["password"])
            elif action == "sync":
                if status["enabled"]:
                    raise ValueError("Manual sync is only available while stopped")
                return sync_once(self.env.CACHE)
            elif action == "batch_probe":
                # A failing second statement must roll back the first statement.
                run_sync(
                    self.env.CACHE.prepare(
                        "CREATE TABLE IF NOT EXISTS edge_batch_probe (id INTEGER PRIMARY KEY)"
                    ).run()
                )
                run_sync(self.env.CACHE.prepare("DELETE FROM edge_batch_probe").run())
                failed = False
                try:
                    run_sync(
                        self.env.CACHE.batch(
                            [
                                self.env.CACHE.prepare("INSERT INTO edge_batch_probe VALUES (1)"),
                                self.env.CACHE.prepare("INSERT INTO edge_batch_probe VALUES (1)"),
                            ]
                        )
                    )
                except Exception:
                    failed = True
                result = run_sync(
                    self.env.CACHE.prepare("SELECT count(*) AS n FROM edge_batch_probe").all()
                )
                return {"ok": failed and result["results"][0]["n"] == 0}
            else:
                raise ValueError("Unknown control action")
            return status

    async def alarm(self, alarm_info=None):
        import edge.wsgi  # noqa: F401
        from edge.sync import sync_once

        async with self.lock:
            status = await self.ctx.storage.get("status") or {}
            if not status.get("enabled"):
                return
            started = now_ms()
            status["cycle_gap_ms"] = started - status.get("started_ms", started)
            try:
                result = sync_once(self.env.CACHE)
                status.update(
                    failures=0,
                    last_cycle=result,
                    last_success_ms=now_ms(),
                    error=None,
                    error_sqlstate=None,
                )
            except Exception as error:
                # Do not persist exception strings: drivers can include source credentials.
                status.update(
                    failures=status.get("failures", 0) + 1,
                    error=type(error).__name__,
                    error_sqlstate=getattr(error, "sqlstate", None)
                    or getattr(error.__cause__, "sqlstate", None),
                )
            status["started_ms"] = started
            status["finished_ms"] = now_ms()
            await self.ctx.storage.put("status", status)
            await self.ctx.storage.setAlarm(
                next_alarm(
                    started,
                    now_ms(),
                    interval_ms=status.get("interval_ms", 1000),
                    failures=status["failures"],
                )
            )

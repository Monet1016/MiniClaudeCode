from __future__ import annotations

from pathlib import Path

from cron_core import CronStore
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    return {}


def run(payload, context: ToolContext):
    del payload
    runtime = context.runtime or {}
    store = runtime.get("cron_store")
    if not isinstance(store, CronStore):
        store = CronStore(Path(context.cwd) / ".scheduled_tasks.json")
    jobs = store.list_jobs()
    if not jobs:
        return ok("No cron jobs.")
    return ok(
        "\n".join(
            f"  {job.id}: '{job.cron}' -> {job.prompt[:40]} "
            f"[{'recurring' if job.recurring else 'one-shot'}, "
            f"{'durable' if job.durable else 'session'}]"
            for job in jobs
        )
    )


TOOL = ToolDefinition(
    name="list_crons",
    description="List registered cron jobs.",
    input_schema={"type": "object", "properties": {}, "required": []},
    validator=validate,
    run=run,
)

from __future__ import annotations

from pathlib import Path

from cron_core import CronStore
from tooling import ToolContext, ToolDefinition
from tools.common import ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise TypeError("job_id must be a non-empty string")
    return {"job_id": job_id.strip()}


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    store = runtime.get("cron_store")
    if not isinstance(store, CronStore):
        store = CronStore(Path(context.cwd) / ".scheduled_tasks.json")
    return ok(store.cancel_job(payload["job_id"]))


TOOL = ToolDefinition(
    name="cancel_cron",
    description="Cancel a cron job by ID.",
    input_schema={
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
    validator=validate,
    run=run,
)

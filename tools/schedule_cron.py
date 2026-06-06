from __future__ import annotations

from pathlib import Path

from cron_core import CronStore
from tooling import ToolContext, ToolDefinition
from tools.common import fail, ok


def validate(payload):
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")
    cron = payload.get("cron")
    prompt = payload.get("prompt")
    if not isinstance(cron, str) or not cron.strip():
        raise TypeError("cron must be a non-empty string")
    if not isinstance(prompt, str) or not prompt.strip():
        raise TypeError("prompt must be a non-empty string")
    recurring = payload.get("recurring", True)
    durable = payload.get("durable", True)
    if not isinstance(recurring, bool):
        raise TypeError("recurring must be a boolean")
    if not isinstance(durable, bool):
        raise TypeError("durable must be a boolean")
    return {
        "cron": cron.strip(),
        "prompt": prompt.strip(),
        "recurring": recurring,
        "durable": durable,
    }


def run(payload, context: ToolContext):
    runtime = context.runtime or {}
    store = runtime.get("cron_store")
    if not isinstance(store, CronStore):
        store = CronStore(Path(context.cwd) / ".scheduled_tasks.json")
    result = store.schedule_job(
        payload["cron"],
        payload["prompt"],
        recurring=payload.get("recurring", True),
        durable=payload.get("durable", True),
    )
    if isinstance(result, str):
        return fail(f"Error: {result}")
    return ok(f"Scheduled {result.id}: '{payload['cron']}' -> {payload['prompt']}")


TOOL = ToolDefinition(
    name="schedule_cron",
    description=(
        "Schedule a cron job. cron is 5-field: min hour dom month dow. "
        "For one-shot reminders, compute the target minute and set recurring=false."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cron": {"type": "string"},
            "prompt": {"type": "string"},
            "recurring": {"type": "boolean"},
            "durable": {"type": "boolean"},
        },
        "required": ["cron", "prompt"],
    },
    validator=validate,
    run=run,
)

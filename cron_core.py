from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool
    durable: bool


class CronStore:
    def __init__(self, durable_path: str | Path) -> None:
        self.durable_path = Path(durable_path)
        self.scheduled_jobs: dict[str, CronJob] = {}
        self.cron_queue: list[CronJob] = []
        self.cron_lock = threading.Lock()
        self._last_fired: dict[str, str] = {}
        self.load_durable_jobs()

    def _cron_field_matches(self, field: str, value: int) -> bool:
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            return step > 0 and value % step == 0
        if "," in field:
            return any(self._cron_field_matches(part.strip(), value) for part in field.split(","))
        if "-" in field:
            lo, hi = field.split("-", 1)
            return int(lo) <= value <= int(hi)
        return value == int(field)

    def cron_matches(self, cron_expr: str, dt: datetime) -> bool:
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return False
        minute, hour, dom, month, dow = fields
        dow_val = (dt.weekday() + 1) % 7
        minute_ok = self._cron_field_matches(minute, dt.minute)
        hour_ok = self._cron_field_matches(hour, dt.hour)
        dom_ok = self._cron_field_matches(dom, dt.day)
        month_ok = self._cron_field_matches(month, dt.month)
        dow_ok = self._cron_field_matches(dow, dow_val)
        if not (minute_ok and hour_ok and month_ok):
            return False
        if dom == "*" and dow == "*":
            return True
        if dom == "*":
            return dow_ok
        if dow == "*":
            return dom_ok
        return dom_ok or dow_ok

    def _validate_cron_field(self, field: str, lo: int, hi: int) -> str | None:
        if field == "*":
            return None
        if field.startswith("*/"):
            step = field[2:]
            if not step.isdigit() or int(step) <= 0:
                return f"Invalid step: {field}"
            return None
        if "," in field:
            for part in field.split(","):
                error = self._validate_cron_field(part.strip(), lo, hi)
                if error:
                    return error
            return None
        if "-" in field:
            left, right = field.split("-", 1)
            if not left.isdigit() or not right.isdigit():
                return f"Invalid range: {field}"
            start, end = int(left), int(right)
            if start < lo or start > hi or end < lo or end > hi:
                return f"Range {field} out of bounds [{lo}-{hi}]"
            if start > end:
                return f"Range start > end: {field}"
            return None
        if not field.isdigit():
            return f"Invalid field: {field}"
        value = int(field)
        if value < lo or value > hi:
            return f"Value {value} out of bounds [{lo}-{hi}]"
        return None

    def validate_cron(self, cron_expr: str) -> str | None:
        fields = cron_expr.strip().split()
        if len(fields) != 5:
            return f"Expected 5 fields, got {len(fields)}"
        bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
        names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
        for field, (lo, hi), name in zip(fields, bounds, names):
            error = self._validate_cron_field(field, lo, hi)
            if error:
                return f"{name}: {error}"
        return None

    def save_durable_jobs(self) -> None:
        self.durable_path.parent.mkdir(parents=True, exist_ok=True)
        durable = [asdict(job) for job in self.scheduled_jobs.values() if job.durable]
        self.durable_path.write_text(json.dumps(durable, indent=2), encoding="utf-8")

    def load_durable_jobs(self) -> None:
        if not self.durable_path.exists():
            return
        try:
            for item in json.loads(self.durable_path.read_text(encoding="utf-8")):
                job = CronJob(**item)
                if not self.validate_cron(job.cron):
                    self.scheduled_jobs[job.id] = job
        except Exception:
            return

    def schedule_job(
        self,
        cron: str,
        prompt: str,
        recurring: bool = True,
        durable: bool = True,
    ) -> CronJob | str:
        error = self.validate_cron(cron)
        if error:
            return error
        job = CronJob(
            id=f"cron_{random.randint(0, 999999):06d}",
            cron=cron,
            prompt=prompt,
            recurring=recurring,
            durable=durable,
        )
        with self.cron_lock:
            self.scheduled_jobs[job.id] = job
        if durable:
            self.save_durable_jobs()
        return job

    def cancel_job(self, job_id: str) -> str:
        with self.cron_lock:
            job = self.scheduled_jobs.pop(job_id, None)
        if not job:
            return f"Job {job_id} not found"
        if job.durable:
            self.save_durable_jobs()
        return f"Cancelled {job_id}"

    def consume_cron_queue(self) -> list[CronJob]:
        with self.cron_lock:
            fired = list(self.cron_queue)
            self.cron_queue.clear()
        return fired

    def list_jobs(self) -> list[CronJob]:
        with self.cron_lock:
            return list(self.scheduled_jobs.values())

    def cron_scheduler_tick(self, now: datetime) -> None:
        marker = now.strftime("%Y-%m-%d %H:%M")
        with self.cron_lock:
            for job in list(self.scheduled_jobs.values()):
                try:
                    if self.cron_matches(job.cron, now) and self._last_fired.get(job.id) != marker:
                        self.cron_queue.append(job)
                        self._last_fired[job.id] = marker
                        if not job.recurring:
                            self.scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                self.save_durable_jobs()
                except Exception:
                    continue

    def cron_scheduler_loop(self) -> None:
        while True:
            time.sleep(1)
            self.cron_scheduler_tick(datetime.now())

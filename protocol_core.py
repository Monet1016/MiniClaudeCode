from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


@dataclass
class ProtocolState:
    request_id: str
    type: str
    sender: str
    target: str
    status: str
    payload: str
    created_at: float = field(default_factory=time.time)


class ProtocolStore:
    def __init__(self) -> None:
        self.pending_requests: dict[str, ProtocolState] = {}
        self.pending = self.pending_requests

    def new_request_id(self) -> str:
        return f"req_{random.randint(0, 999999):06d}"

    def create_plan_request(self, sender: str, target: str, payload: str) -> str:
        request_id = self.new_request_id()
        self.pending_requests[request_id] = ProtocolState(
            request_id=request_id,
            type="plan_approval",
            sender=sender,
            target=target,
            status="pending",
            payload=payload,
        )
        return request_id

    def create_shutdown_request(self, sender: str, target: str) -> str:
        request_id = self.new_request_id()
        self.pending_requests[request_id] = ProtocolState(
            request_id=request_id,
            type="shutdown",
            sender=sender,
            target=target,
            status="pending",
            payload="",
        )
        return request_id

    def match_response(self, response_type: str, request_id: str, approve: bool) -> None:
        state = self.pending_requests.get(request_id)
        if not state:
            return
        if state.type == "shutdown" and response_type != "shutdown_response":
            return
        if state.type == "plan_approval" and response_type != "plan_approval_response":
            return
        state.status = "approved" if approve else "rejected"

    def review_plan(self, request_id: str, approve: bool, feedback: str = "") -> str:
        state = self.pending_requests.get(request_id)
        if not state:
            return f"Request {request_id} not found"
        state.status = "approved" if approve else "rejected"
        del feedback
        return f"Plan {'approved' if approve else 'rejected'}"

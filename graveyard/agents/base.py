"""Shared pieces for agents: the evidence contract and the run trace.

Agents never call each other. Each one reads the patent record (and earlier agents'
outputs, passed in by the orchestrator) and writes evidence records to a shared store.
The Report agent may only make claims that point at one of those records.
"""

import time
from dataclasses import asdict, dataclass, field


@dataclass
class Evidence:
    id: str
    agent: str
    claim: str
    source: str            # URL or named public record
    method: str            # how the claim was produced
    confidence: str = "high"
    data: dict = field(default_factory=dict)


class EvidenceStore:
    def __init__(self):
        self.items: list[Evidence] = []

    def add(self, agent: str, claim: str, source: str, method: str, confidence: str = "high", **data) -> str:
        eid = f"E{len(self.items) + 1}"
        self.items.append(Evidence(eid, agent, claim, source, method, confidence, data))
        return eid

    def by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.items}

    def for_agent(self, agent: str) -> list[Evidence]:
        return [e for e in self.items if e.agent == agent]

    def to_list(self) -> list[dict]:
        return [asdict(e) for e in self.items]


class Trace:
    """What each agent did, shown in the demo as the 'show your work' panel."""

    def __init__(self, on_step=None):
        self.steps: list[dict] = []
        self.on_step = on_step

    def run(self, agent: str, task: str, fn, *args, **kwargs):
        t0 = time.monotonic()
        step = {"agent": agent, "task": task, "status": "running"}
        if self.on_step:
            self.on_step(step)
        try:
            out = fn(*args, **kwargs)
            step.update(status="done", summary=out.get("summary") if isinstance(out, dict) else None)
        except Exception as e:  # an agent failing should not kill the report
            step.update(status="failed", summary=f"{type(e).__name__}: {e}")
            out = None
        step["seconds"] = round(time.monotonic() - t0, 2)
        self.steps.append(step)
        if self.on_step:
            self.on_step(step)
        return out

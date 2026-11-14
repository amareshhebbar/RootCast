"""Decision graph and the audit of a failed run.

Baseline causal engine: build the graph from depends_on, find the step
where the run failed, walk back through everything that fed it, and name the
earliest ancestor that scoring flagged as the CAUSE. The divergence walk is
owned by the causal engine track (feat/causal-engine) and is expected to grow
more signals. The audit result it returns is the contract the CLI renders.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .schema import Step, Trace
from .scoring import FAIL, WARN, Baseline, Score, score_trace

CAUSE = "cause"


@dataclass
class DecisionGraph:
    steps: dict[str, Step]
    order: dict[str, int]
    parents: dict[str, list[str]]
    children: dict[str, list[str]]

    @classmethod
    def build(cls, trace: Trace) -> "DecisionGraph":
        steps = {s.id: s for s in trace.steps}
        order = {s.id: i for i, s in enumerate(trace.steps)}
        parents = {s.id: [d for d in s.depends_on if d in steps] for s in trace.steps}
        children: dict[str, list[str]] = {s.id: [] for s in trace.steps}
        for sid, deps in parents.items():
            for dep in deps:
                children[dep].append(sid)
        return cls(steps, order, parents, children)

    def ancestors(self, step_id: str) -> list[str]:
        """Every step that fed step_id, directly or not, in trace order."""
        seen: set[str] = set()
        queue = deque(self.parents.get(step_id, []))
        while queue:
            sid = queue.popleft()
            if sid in seen:
                continue
            seen.add(sid)
            queue.extend(self.parents.get(sid, []))
        return sorted(seen, key=self.order.__getitem__)

    def path(self, start: str, end: str) -> list[str]:
        """Shortest chain of edges from start down to end, or [] if none."""
        prev: dict[str, Optional[str]] = {start: None}
        queue = deque([start])
        while queue:
            sid = queue.popleft()
            if sid == end:
                chain = []
                node: Optional[str] = sid
                while node is not None:
                    chain.append(node)
                    node = prev[node]
                return chain[::-1]
            for child in self.children.get(sid, []):
                if child not in prev:
                    prev[child] = sid
                    queue.append(child)
        return []


@dataclass
class AuditResult:
    trace: Trace
    scores: dict[str, Score]
    failure: Optional[str] = None
    cause: Optional[str] = None
    chain: list[str] = field(default_factory=list)

    def tag(self, step_id: str) -> str:
        """The audit tag for a step: cause, fail, warn or pass."""
        if step_id == self.cause and self.cause != self.failure:
            return CAUSE
        return self.scores[step_id].status

    @property
    def summary(self) -> Optional[str]:
        if self.failure is None:
            return None
        failed = self.trace.get(self.failure)
        if self.cause is None or self.cause == self.failure:
            return failed.name + " failed and nothing upstream looks wrong"
        cause = self.trace.get(self.cause)
        problems = self.scores[self.cause].problems
        why = problems[0].message if problems else "looks wrong"
        return cause.name + ": " + why + ", and that fed " + failed.name

    def to_dict(self) -> dict:
        return {
            "run_id": self.trace.run_id,
            "status": self.trace.status,
            "failure": self.failure,
            "cause": self.cause,
            "chain": self.chain,
            "summary": self.summary,
            "steps": [dict(self.scores[s.id].to_dict(), tag=self.tag(s.id)) for s in self.trace.steps],
        }


def find_failure(trace: Trace, scores: dict[str, Score]) -> Optional[str]:
    """The step where the run visibly failed: the last FAIL step, else the last step of a failed run."""
    failing = [s.id for s in trace.steps if scores[s.id].status == FAIL]
    if failing:
        return failing[-1]
    if trace.status == "fail" and trace.steps:
        return trace.steps[-1].id
    return None


def find_cause(graph: DecisionGraph, failure: str, scores: dict[str, Score]) -> str:
    """Earliest ancestor of the failure that scoring flags WARN or FAIL, else the failure itself."""
    for sid in graph.ancestors(failure):
        if scores[sid].status in (WARN, FAIL):
            return sid
    return failure


def audit(trace: Trace, baseline: Optional[Baseline] = None) -> AuditResult:
    scores = score_trace(trace, baseline)
    result = AuditResult(trace=trace, scores=scores)
    result.failure = find_failure(trace, scores)
    if result.failure is not None:
        graph = DecisionGraph.build(trace)
        result.cause = find_cause(graph, result.failure, scores)
        result.chain = graph.path(result.cause, result.failure) or [result.failure]
    return result

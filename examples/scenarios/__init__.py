from . import rag_lookup, stale_policy, tool_args

SCENARIOS = {
    "stale_policy": stale_policy,
    "rag_lookup": rag_lookup,
    "tool_args": tool_args,
}


class TickClock:
    def __init__(self, start: float = 1767225600.0, tick: float = 0.25):
        self._now = start
        self._tick = tick

    def __call__(self) -> float:
        value = self._now
        self._now = round(self._now + self._tick, 6)
        return value

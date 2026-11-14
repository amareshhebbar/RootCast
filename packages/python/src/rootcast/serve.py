"""rootcast serve: the local backend the web UI talks to.

One engine, two front doors. The UI never reimplements scoring, audit or
replay: it posts the trace here and this module calls the very same audit()
and replay() functions the CLI uses.

Endpoints (JSON):

  GET  /                  the UI (ui/index.html)
  GET  /api/info          version, sample traces, loaded replay agents
  GET  /api/sample?name=  one sample trace
  POST /api/audit         {"trace": {...}}                  -> audit, graph edges, matched agent
  POST /api/replay        {"trace": {...}, "sets": ["step2.output=..."]}
                                                            -> replay result and audit of the replayed run

Binds to 127.0.0.1 only. Agent modules are Python files you chose to load
with --agent (or the repo's own examples), never anything sent by the page.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .causal import audit
from .recorder import Recorder
from .replay import Agent, ExternalCallError, ReplayError, load_agent_module, parse_set, replay
from .schema import TRACE_SUFFIX, Trace, validate

MAX_BODY = 16 * 1024 * 1024
DEFAULT_PORT = 8765

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))


def find_ui() -> Optional[str]:
    """The UI file: bundled in the package, else ui/ in a source checkout."""
    for path in (os.path.join(_HERE, "ui", "index.html"), os.path.join(_REPO, "ui", "index.html")):
        if os.path.exists(path):
            return path
    return None


@dataclass
class LoadedAgent:
    path: str
    factory: Callable
    values: dict
    steps: list[str]

    def info(self) -> dict:
        return {"path": self.path, "steps": self.steps, "values": sorted(self.values)}


def load_agent(path: str) -> LoadedAgent:
    module = load_agent_module(path)
    built = module.replay_agent(Recorder(run_id="probe", infer=False))
    names = sorted(built.entries if isinstance(built, Agent) else built)
    return LoadedAgent(path, module.replay_agent, dict(getattr(module, "REPLAY_VALUES", {})), names)


@dataclass
class ServerState:
    samples: dict[str, str] = field(default_factory=dict)
    agents: list[LoadedAgent] = field(default_factory=list)
    ui_path: Optional[str] = None

    def match_agent(self, trace: Trace) -> Optional[LoadedAgent]:
        """The loaded agent that registers the most of this trace's step names."""
        names = {s.name for s in trace.steps}
        best, best_hits = None, 0
        for agent in self.agents:
            hits = len(names & set(agent.steps))
            if hits > best_hits:
                best, best_hits = agent, hits
        return best


def default_state(trace_dirs: list[str], agent_paths: list[str]) -> ServerState:
    state = ServerState(ui_path=find_ui())
    for d in trace_dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(TRACE_SUFFIX):
                state.samples.setdefault(name[: -len(TRACE_SUFFIX)], os.path.join(d, name))
    for path in agent_paths:
        state.agents.append(load_agent(path))
    return state


# API ---------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.payload = dict(error=message, **extra)


def _trace_from(body: dict) -> Trace:
    data = body.get("trace")
    errors = validate(data)
    if errors:
        raise ApiError(400, "not a valid Rootcast trace: " + "; ".join(errors[:5]), errors=errors)
    return Trace.from_dict(data)


def _edges(trace: Trace) -> list[dict]:
    inferred = trace.meta.get("inferred_depends_on", {}) if isinstance(trace.meta, dict) else {}
    edges = []
    for step in trace.steps:
        for dep in step.depends_on:
            edges.append({"from": dep, "to": step.id, "inferred": dep in inferred.get(step.id, [])})
    return edges


def api_info(state: ServerState) -> dict:
    samples = []
    for name, path in state.samples.items():
        try:
            trace = Trace.load(path)
            samples.append({"name": name, "run_id": trace.run_id, "status": trace.status})
        except (OSError, ValueError, KeyError):
            continue
    return {"version": __version__, "samples": samples, "agents": [a.info() for a in state.agents]}


def api_sample(state: ServerState, name: str) -> dict:
    path = state.samples.get(name)
    if path is None:
        raise ApiError(404, "no sample named " + name)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def api_audit(state: ServerState, body: dict) -> dict:
    trace = _trace_from(body)
    agent = state.match_agent(trace)
    return {
        "trace": trace.to_dict(),
        "audit": audit(trace).to_dict(),
        "edges": _edges(trace),
        "agent": agent.info() if agent else None,
    }


def api_replay(state: ServerState, body: dict) -> dict:
    trace = _trace_from(body)
    sets = body.get("sets") or []
    if not isinstance(sets, list) or not all(isinstance(s, str) for s in sets):
        raise ApiError(400, "sets must be a list of STEP.output=VALUE strings")
    agent = state.match_agent(trace)
    try:
        injections = [parse_set(spec, trace, agent.values if agent else {}) for spec in sets]
        result = replay(trace, injections, agent.factory if agent else None)
    except ExternalCallError as exc:
        raise ApiError(409, str(exc), external_step=exc.step_id)
    except ReplayError as exc:
        raise ApiError(422, str(exc))
    return {"result": result.to_dict(), "audit": audit(result.replayed).to_dict()}


# HTTP --------------------------------------------------------------------


def make_handler(state: ServerState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "rootcast/" + __version__

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

        def _guard(self, fn) -> None:
            try:
                self._json(200, fn())
            except ApiError as exc:
                self._json(exc.status, exc.payload)
            except Exception as exc:  # surface engine bugs to the page instead of a dead socket
                self._json(500, {"error": type(exc).__name__ + ": " + str(exc)})

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                if state.ui_path is None:
                    self._send(404, b"UI not found", "text/plain")
                    return
                with open(state.ui_path, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif url.path == "/api/info":
                self._guard(lambda: api_info(state))
            elif url.path == "/api/sample":
                name = parse_qs(url.query).get("name", [""])[0]
                self._guard(lambda: api_sample(state, name))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            url = urlparse(self.path)
            routes = {"/api/audit": api_audit, "/api/replay": api_replay}
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self.close_connection = True
                self._json(413, {"error": "trace too large"})
                return
            # Read the body before answering, even for an unknown route: replying with
            # unread request bytes makes some clients (Windows) see a reset connection.
            raw = self.rfile.read(length)
            if url.path not in routes:
                self._json(404, {"error": "not found"})
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._json(400, {"error": "body is not JSON"})
                return
            if not isinstance(body, dict):
                self._json(400, {"error": "body must be a JSON object"})
                return
            self._guard(lambda: routes[url.path](state, body))

    return Handler


def make_server(state: ServerState, port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(state))


def start_in_thread(state: ServerState, port: int = 0) -> ThreadingHTTPServer:
    server = make_server(state, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def default_dirs() -> tuple[list[str], list[str]]:
    """The repo's sample traces and scenario agents, when running from a checkout."""
    traces, agents = [], []
    for root in (os.getcwd(), _REPO):
        t = os.path.join(root, "examples", "traces")
        a = os.path.join(root, "examples", "scenarios")
        if os.path.isdir(t) and not traces:
            traces.append(t)
        if os.path.isdir(a) and not agents:
            agents = [
                os.path.join(a, n) for n in sorted(os.listdir(a)) if n.endswith(".py") and not n.startswith("_")
            ]
    return traces, agents


def serve(args) -> int:
    traces, agents = default_dirs()
    if args.traces:
        traces = args.traces + traces
    if args.agent:
        agents = args.agent
    store = os.path.join(os.environ.get("ROOTCAST_DIR") or ".rootcast", "runs")
    state = default_state(traces + [store], agents)
    if state.ui_path is None:
        print("serve: ui/index.html not found", file=sys.stderr)
        return 2
    try:
        server = make_server(state, args.port)
    except OSError as exc:
        print("serve: cannot listen on port " + str(args.port) + ": " + str(exc), file=sys.stderr)
        return 2
    url = "http://127.0.0.1:" + str(server.server_address[1]) + "/"
    print("rootcast ui on " + url)
    print("  samples: " + (", ".join(state.samples) or "none"))
    print("  agents:  " + (", ".join(os.path.basename(a.path) for a in state.agents) or "none"))
    print("  ctrl+c to stop")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

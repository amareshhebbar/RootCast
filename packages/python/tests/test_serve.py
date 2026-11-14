"""rootcast serve and the web UI.

API tests always run. Browser tests drive the real ui/index.html in headless
Chrome or Edge. They skip when no browser is found, unless
ROOTCAST_REQUIRE_BROWSER=1 (set in CI), in which case they fail.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

import pytest

from rootcast import Trace, audit, parse_set, replay
from rootcast.replay import load_agent_module
from rootcast.serve import ServerState, default_dirs, default_state, find_ui, start_in_thread

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TRACES = os.path.join(ROOT, "examples", "traces")
SCENARIOS = os.path.join(ROOT, "examples", "scenarios")


def _state(ui_path=None):
    traces, agents = default_dirs()
    state = default_state(traces, agents)
    if ui_path:
        state.ui_path = ui_path
    return state


@pytest.fixture(scope="module")
def server():
    srv = start_in_thread(_state())
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as res:
        return res.status, res.read()


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def _sample(name):
    with open(os.path.join(TRACES, name + ".rootcast.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


# API ----------------------------------------------------------------------------


def test_ui_is_served(server):
    status, body = _get(server + "/")
    assert status == 200 and b"<title>Rootcast</title>" in body
    assert find_ui() is not None


def test_info_lists_samples_and_agents(server):
    _, body = _get(server + "/api/info")
    info = json.loads(body)
    assert {s["name"] for s in info["samples"]} >= {"stale_policy", "rag_lookup", "tool_args"}
    assert any("policy_2026" in a["values"] for a in info["agents"])


def test_sample_endpoint_rejects_unknown_names(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server + "/api/sample?name=../../etc/passwd")
    assert err.value.code == 404


def test_audit_endpoint_is_the_engine_audit(server):
    status, out = _post(server + "/api/audit", {"trace": _sample("stale_policy")})
    assert status == 200
    assert out["audit"] == audit(Trace.from_dict(_sample("stale_policy"))).to_dict()
    assert out["audit"]["cause"] == "step2"
    assert {"from": "step2", "to": "step3", "inferred": True} in out["edges"]
    assert out["agent"]["path"].endswith("stale_policy.py")


def test_ui_replay_equals_cli_replay(server):
    """One engine, two front doors: the endpoint returns exactly what replay() gives the CLI."""
    sets = ["step2.output=policy_2026"]
    status, out = _post(server + "/api/replay", {"trace": _sample("stale_policy"), "sets": sets})
    assert status == 200
    trace = Trace.from_dict(_sample("stale_policy"))
    module = load_agent_module(os.path.join(SCENARIOS, "stale_policy.py"))
    direct = replay(trace, [parse_set(s, trace, module.REPLAY_VALUES) for s in sets], module.replay_agent)
    assert out["result"] == json.loads(json.dumps(direct.to_dict()))
    assert out["result"]["status"] == {"before": "fail", "after": "pass", "flipped": True}
    assert out["audit"]["failure"] is None


def test_replay_endpoint_reports_external_calls(server):
    status, out = _post(server + "/api/replay", {"trace": _sample("tool_args"), "sets": ["step3.output=fixed_plan"]})
    assert status == 409 and out["external_step"] == "step4"


def test_bad_requests(server):
    assert _post(server + "/api/audit", {"trace": {"run_id": "x"}})[0] == 400
    assert _post(server + "/api/replay", {"trace": _sample("stale_policy"), "sets": "nope"})[0] == 400
    assert _post(server + "/api/replay", {"trace": _sample("stale_policy"), "sets": ["step9.output=1"]})[0] == 422
    assert _post(server + "/api/nope", {})[0] == 404


def test_trace_without_a_matching_agent_still_audits():
    state = ServerState(samples={}, agents=[], ui_path=find_ui())
    srv = start_in_thread(state)
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        status, out = _post(base + "/api/audit", {"trace": _sample("stale_policy")})
        assert status == 200 and out["agent"] is None
        status, out = _post(base + "/api/replay", {"trace": _sample("stale_policy"), "sets": ["step2.output=1"]})
        assert status == 422 and "--agent" in out["error"]
    finally:
        srv.shutdown()


# Browser ------------------------------------------------------------------------


def _browser():
    candidates = [os.environ.get("ROOTCAST_BROWSER")]
    candidates += [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")]
    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    if os.environ.get("ROOTCAST_REQUIRE_BROWSER") == "1":
        pytest.fail("no Chrome, Chromium or Edge found for the UI test")
    pytest.skip("no Chrome, Chromium or Edge found")


def _dom(browser, url):
    args = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--user-data-dir=" + tempfile.mkdtemp(prefix="rootcast-ui-"), "--virtual-time-budget=15000",
            "--dump-dom", url]
    if sys.platform.startswith("linux"):
        args.insert(1, "--no-sandbox")
    return subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=120).stdout


def _tags(dom):
    return dict(re.findall(r'data-id="(step\d+)" data-tag="(\w+)"', dom))


def _banner(dom):
    m = re.search(r'id="banner" data-status="(\w+)"', dom)
    return m and m.group(1)


def test_ui_renders_stale_policy_with_cause_highlighted(server):
    dom = _dom(_browser(), server + "/?sample=stale_policy")
    assert 'data-ready="true"' in dom
    assert _banner(dom) == "fail"
    assert _tags(dom) == {"step1": "pass", "step2": "cause", "step3": "pass", "step4": "fail"}
    assert "ROOT CAUSE" in dom and "Chain: step2 → step3 → step4" in dom


def test_ui_replay_deep_link_flips_banner_to_pass(server):
    dom = _dom(_browser(), server + "/?sample=stale_policy&set=step2.output%3Dpolicy_2026")
    assert _banner(dom) == "pass"
    changes = dict(re.findall(r'data-id="(step\d+)" data-tag="\w+" data-change="(\w+)"', dom))
    assert changes == {"step1": "unchanged", "step2": "injected", "step3": "recomputed", "step4": "recomputed"}
    assert "Cause proven." in dom


CLICK_SCRIPT = """
<script>
(async () => {
  const wait = (f) => new Promise((r) => { const t = setInterval(() => { if (f()) { clearInterval(t); r(); } }, 25); });
  await wait(() => document.body.dataset.ready === "true");
  [...document.querySelectorAll("#drop-samples button")].find((b) => b.textContent === "stale_policy").click();
  await wait(() => document.querySelector('.node[data-id="step2"]'));
  document.body.dataset.before = document.getElementById("banner").dataset.status + ":" +
    document.querySelector('.node[data-id="step2"]').dataset.tag;
  document.querySelector('.node[data-id="step2"]').dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await wait(() => document.querySelector("#detail h2")?.textContent === "lookup_policy");
  const picker = document.querySelector("#detail select");
  picker.value = "policy_2026";
  picker.dispatchEvent(new Event("change"));
  [...document.querySelectorAll("#detail button")].find((b) => b.textContent === "Run replay").click();
  await wait(() => document.getElementById("banner").dataset.status === "pass");
  document.body.dataset.clicked = "done";
})();
</script>
"""


def test_ui_click_to_replay_flips_banner(tmp_path):
    """Drive the real UI with clicks: open sample, click the cause, pick a value, run replay."""
    with open(find_ui(), "r", encoding="utf-8") as fh:
        page = fh.read().replace("</body>", CLICK_SCRIPT + "</body>")
    harness = tmp_path / "index.html"
    harness.write_text(page, encoding="utf-8")
    srv = start_in_thread(_state(str(harness)))
    try:
        dom = _dom(_browser(), "http://127.0.0.1:%d/" % srv.server_address[1])
    finally:
        srv.shutdown()
    assert 'data-before="fail:cause"' in dom
    assert 'data-clicked="done"' in dom
    assert _banner(dom) == "pass"

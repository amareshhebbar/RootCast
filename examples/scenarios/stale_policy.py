from rootcast import Recorder, current_step

RUN_ID = "refund-7af3"
EXPECTED = {"fail": "step4", "cause": "step2"}

POLICIES = {
    2024: {"source": "policy_2024", "year": 2024, "window_days": 90},
    2026: {"source": "policy_2026", "year": 2026, "window_days": 30},
}


def build(rec: Recorder):
    @rec.record(kind="tool")
    def read_order(order_id):
        return {"id": order_id, "year": 2026, "amount": 129.0, "days_since_purchase": 45}

    @rec.record(kind="tool")
    def lookup_policy(query):
        return dict(POLICIES[2024], query=query)

    @rec.record(kind="decision")
    def decide_refund(order, policy):
        allowed = order["days_since_purchase"] <= policy["window_days"]
        return {"allowed": allowed, "window_days": policy["window_days"], "policy_source": policy["source"]}

    @rec.record(kind="tool")
    def issue_refund(order, decision):
        actual = POLICIES[order["year"]]["window_days"]
        if decision["allowed"] and order["days_since_purchase"] > actual:
            current_step().status("fail")
            current_step().error("refund issued outside the " + str(actual) + " day policy window")
            return {"status": "issued", "order": order["id"], "violation": "outside_window"}
        return {"status": "issued" if decision["allowed"] else "denied", "order": order["id"]}

    return read_order, lookup_policy, decide_refund, issue_refund


def run(out_path, clock=None):
    rec = Recorder(run_id=RUN_ID, meta={"framework": "generic", "scenario": "stale policy"}, clock=clock)
    read_order, lookup_policy, decide_refund, issue_refund = build(rec)
    order = read_order(4417)
    policy = lookup_policy("refund window")
    decision = decide_refund(order, policy)
    issue_refund(order, decision)
    return rec.save(out_path)

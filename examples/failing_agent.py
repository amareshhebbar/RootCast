from rootcast import Recorder


def get_order(order_id):
    return {"id": order_id, "year": 2026}


def search_policy(query):
    return {"query": query, "source": "policy_2024", "window_days": 90}


def decide_refund(order, policy):
    return {"allowed": True, "window_days": policy["window_days"]}


def issue_refund(order):
    return {"status": "ok", "order": order["id"]}


def run():
    rec = Recorder(run_id="refund-7af3", meta={"framework": "generic", "scenario": "stale policy"})

    with rec.step("read_order", kind="tool") as s:
        order = get_order(4417)
        s.output(order)

    with rec.step("lookup_policy", kind="tool", depends_on=["step1"]) as s:
        s.input({"query": "refund window"})
        policy = search_policy("refund window")
        s.output(policy)

    with rec.step("decide_refund", kind="decision", depends_on=["step1", "step2"]) as s:
        decision = decide_refund(order, policy)
        s.output(decision)

    with rec.step("issue_refund", kind="tool", depends_on=["step3"]) as s:
        result = issue_refund(order)
        s.output(result)
        s.status("fail")

    rec.mark("fail")
    path = rec.save("refund-7af3.rootcast.json")
    print("wrote " + path)


if __name__ == "__main__":
    run()

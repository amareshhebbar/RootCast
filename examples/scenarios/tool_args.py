from rootcast import Agent, Recorder

RUN_ID = "tool-58d2"
EXPECTED = {"fail": "step4", "cause": "step3"}


def build(rec: Recorder):
    @rec.record(kind="tool")
    def read_ticket(ticket_id):
        return {"id": ticket_id, "customer": "acme-corp-eu", "request": "upgrade to pro plan for 25 seats"}

    @rec.record(kind="tool")
    def lookup_account(customer):
        return {"customer": customer, "plan": "basic", "seats": 10}

    @rec.record(kind="llm")
    def plan_action(ticket, account):
        return {"tool": "update_subscription", "args": {"account": account["customer"], "plan": "pro", "seats": "25 seats"}}

    @rec.record(kind="tool")
    def update_subscription(args):
        if not isinstance(args["seats"], int):
            raise TypeError("seats must be an integer, got " + type(args["seats"]).__name__)
        return {"status": "updated", "plan": args["plan"], "seats": args["seats"]}

    return read_ticket, lookup_account, plan_action, update_subscription


# Named values for rootcast replay --set, e.g. --set step3.output=fixed_plan
REPLAY_VALUES = {
    "fixed_plan": {"tool": "update_subscription", "args": {"account": "acme-corp-eu", "plan": "pro", "seats": 25}},
    "updated": {"status": "updated", "plan": "pro", "seats": 25},
}


def replay_agent(rec: Recorder) -> Agent:
    agent = Agent()
    # update_subscription is the billing API: an external call replay must not make.
    for fn in build(rec):
        agent.add(fn)
    return agent


def run(out_path, clock=None):
    rec = Recorder(run_id=RUN_ID, meta={"framework": "generic", "scenario": "tool argument error"}, clock=clock)
    read_ticket, lookup_account, plan_action, update_subscription = build(rec)
    ticket = read_ticket("T-1093")
    account = lookup_account(ticket["customer"])
    action = plan_action(ticket, account)
    try:
        update_subscription(action["args"])
    except TypeError:
        rec.mark("fail")
    return rec.save(out_path)

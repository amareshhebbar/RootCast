// Node ports of examples/scenarios/*.py. Each one records the same agent run
// as its Python twin, so the trace files must come out byte identical.
import { Recorder, currentStep } from "../../packages/node/dist/index.js";

export class TickClock {
  constructor(start = 1767225600.0, tick = 0.25) {
    this.now = start;
    this.tick = tick;
    this.call = this.call.bind(this);
  }

  call() {
    const value = this.now;
    this.now = Math.round((this.now + this.tick) * 1e6) / 1e6;
    return value;
  }
}

const POLICIES = {
  2024: { source: "policy_2024", year: 2024, window_days: 90 },
  2026: { source: "policy_2026", year: 2026, window_days: 30 },
};

function stalePolicy(outPath, clock) {
  const rec = new Recorder({
    runId: "refund-7af3",
    meta: { framework: "generic", scenario: "stale policy" },
    clock,
  });
  const readOrder = rec.record(
    function read_order(order_id) {
      return { id: order_id, year: 2026, amount: 129.0, days_since_purchase: 45 };
    },
    { kind: "tool" }
  );
  const lookupPolicy = rec.record(
    function lookup_policy(query) {
      return { ...POLICIES[2024], query };
    },
    { kind: "tool" }
  );
  const decideRefund = rec.record(
    function decide_refund(order, policy) {
      const allowed = order.days_since_purchase <= policy.window_days;
      return { allowed, window_days: policy.window_days, policy_source: policy.source };
    },
    { kind: "decision" }
  );
  const issueRefund = rec.record(
    function issue_refund(order, decision) {
      const actual = POLICIES[order.year].window_days;
      if (decision.allowed && order.days_since_purchase > actual) {
        currentStep().status("fail");
        currentStep().error("refund issued outside the " + actual + " day policy window");
        return { status: "issued", order: order.id, violation: "outside_window" };
      }
      return { status: decision.allowed ? "issued" : "denied", order: order.id };
    },
    { kind: "tool" }
  );

  const order = readOrder(4417);
  const policy = lookupPolicy("refund window");
  const decision = decideRefund(order, policy);
  issueRefund(order, decision);
  return rec.save(outPath);
}

const CORPUS = [
  { id: "dosage_adult_v3", audience: "adult", text: "Drug X maximum single dose for adults is 400 mg." },
  { id: "dosage_pediatric_v2", audience: "pediatric", text: "Drug X maximum single dose for children is 200 mg." },
];

function ragLookup(outPath, clock) {
  const rec = new Recorder({
    runId: "rag-21c9",
    meta: { framework: "generic", scenario: "rag lookup failure" },
    clock,
  });
  const parseQuestion = rec.record(
    function parse_question(question) {
      return { topic: "drug_x_max_dose", audience: "pediatric" };
    },
    { kind: "llm" }
  );
  const retrieve = rec.record(
    function retrieve(intent, top_k = 1) {
      const ranked = [...CORPUS].sort((a, b) => Number(a.audience !== "adult") - Number(b.audience !== "adult"));
      return { topic: intent.topic, docs: ranked.slice(0, top_k) };
    },
    { kind: "tool" }
  );
  const generateAnswer = rec.record(
    function generate_answer(question, docs) {
      const doc = docs[0];
      const dose = doc.text.split(" is ").pop().replace(/\.+$/, "");
      return { answer: "The maximum single dose is " + dose + ".", citations: [doc.id] };
    },
    { kind: "llm" }
  );
  const checkAnswer = rec.record(
    function check_answer(answer, intent) {
      const cited = answer.citations[0];
      const ok = cited.includes(intent.audience);
      if (!ok) {
        currentStep().status("fail");
        currentStep().error("answer cites " + cited + " but the question is " + intent.audience);
      }
      return { grounded: ok, cited };
    },
    { kind: "decision" }
  );

  const question = "What is the maximum single dose of drug X for a child?";
  const intent = parseQuestion(question);
  const hits = retrieve(intent);
  const answer = generateAnswer(question, hits.docs);
  checkAnswer(answer, intent);
  return rec.save(outPath);
}

function pyTypeName(value) {
  return typeof value === "string" ? "str" : typeof value;
}

async function toolArgs(outPath, clock) {
  const rec = new Recorder({
    runId: "tool-58d2",
    meta: { framework: "generic", scenario: "tool argument error" },
    clock,
  });
  // Async on purpose: proves the wrapper and currentStep work across awaits.
  const readTicket = rec.record(
    async function read_ticket(ticket_id) {
      return { id: ticket_id, customer: "acme-corp-eu", request: "upgrade to pro plan for 25 seats" };
    },
    { kind: "tool" }
  );
  const lookupAccount = rec.record(
    async function lookup_account(customer) {
      return { customer, plan: "basic", seats: 10 };
    },
    { kind: "tool" }
  );
  const planAction = rec.record(
    async function plan_action(ticket, account) {
      return { tool: "update_subscription", args: { account: account.customer, plan: "pro", seats: "25 seats" } };
    },
    { kind: "llm" }
  );
  const updateSubscription = rec.record(
    async function update_subscription(args) {
      if (!Number.isInteger(args.seats)) {
        throw new TypeError("seats must be an integer, got " + pyTypeName(args.seats));
      }
      return { status: "updated", plan: args.plan, seats: args.seats };
    },
    { kind: "tool" }
  );

  const ticket = await readTicket("T-1093");
  const account = await lookupAccount(ticket.customer);
  const action = await planAction(ticket, account);
  try {
    await updateSubscription(action.args);
  } catch (err) {
    if (!(err instanceof TypeError)) throw err;
    rec.mark("fail");
  }
  return rec.save(outPath);
}

export const SCENARIOS = {
  stale_policy: stalePolicy,
  rag_lookup: ragLookup,
  tool_args: toolArgs,
};

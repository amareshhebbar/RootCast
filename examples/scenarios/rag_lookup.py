from rootcast import Agent, Recorder, current_step

RUN_ID = "rag-21c9"
EXPECTED = {"fail": "step4", "cause": "step2"}

CORPUS = [
    {"id": "dosage_adult_v3", "audience": "adult", "text": "Drug X maximum single dose for adults is 400 mg."},
    {"id": "dosage_pediatric_v2", "audience": "pediatric", "text": "Drug X maximum single dose for children is 200 mg."},
]


def build(rec: Recorder):
    @rec.record(kind="llm")
    def parse_question(question):
        return {"topic": "drug_x_max_dose", "audience": "pediatric"}

    @rec.record(kind="tool")
    def retrieve(intent, top_k=1):
        ranked = sorted(CORPUS, key=lambda d: d["audience"] != "adult")
        return {"topic": intent["topic"], "docs": ranked[:top_k]}

    @rec.record(kind="llm")
    def generate_answer(question, docs):
        doc = docs[0]
        dose = doc["text"].split(" is ")[-1].rstrip(".")
        return {"answer": "The maximum single dose is " + dose + ".", "citations": [doc["id"]]}

    @rec.record(kind="decision")
    def check_answer(answer, intent):
        cited = answer["citations"][0]
        ok = intent["audience"] in cited
        if not ok:
            current_step().status("fail")
            current_step().error("answer cites " + cited + " but the question is " + intent["audience"])
        return {"grounded": ok, "cited": cited}

    return parse_question, retrieve, generate_answer, check_answer


# Named values for rootcast replay --set, e.g. --set step2.output=pediatric_docs
REPLAY_VALUES = {"pediatric_docs": {"topic": "drug_x_max_dose", "docs": [CORPUS[1]]}}


def replay_agent(rec: Recorder) -> Agent:
    parse_question, retrieve, generate_answer, check_answer = build(rec)
    agent = Agent()
    agent.add(parse_question)
    agent.add(retrieve)
    # A deterministic template stands in for the model in this sample, so it is safe to re run.
    agent.add(generate_answer, external=False)
    agent.add(check_answer)
    return agent


def run(out_path, clock=None):
    rec = Recorder(run_id=RUN_ID, meta={"framework": "generic", "scenario": "rag lookup failure"}, clock=clock)
    parse_question, retrieve, generate_answer, check_answer = build(rec)
    question = "What is the maximum single dose of drug X for a child?"
    intent = parse_question(question)
    hits = retrieve(intent)
    answer = generate_answer(question, hits["docs"])
    check_answer(answer, intent)
    return rec.save(out_path)

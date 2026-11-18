# Not every AI call needs a paragraph

Most AI demos show a model writing something. This one shows a model deciding something.

Microsoft Foundry now hosts a decision model, `Microsoft-Decision-1.1`, behind a dedicated
decision endpoint. You send a state (text or JSON) and a set of named questions. Each question is
one of three types:

- `choice` - pick one option from a list you define.
- `score` - place the input on an ordered rubric.
- `noul` - return the probability that a yes/no statement is true.

You get back typed answers and probabilities. No prose, no output parsing, no "please respond only
with JSON" prompt engineering.

## What I built

A support-ticket triage demo. One API call asks five questions about the same ticket:

1. Which team should own it? (`choice`)
2. How severe is the impact? (`score`, Cosmetic -> Critical)
3. Is the customer asking for money back? (`noul`)
4. Does the message contain sensitive personal data? (`noul`)
5. Is the customer threatening to churn? (`noul`)

The model returns probabilities. The application decides what to do with them. That second part is
the interesting part: a ticket is auto-routed only when the team decision clears 60% confidence.
Below that, or when PII crosses 50%, or when the category is abuse, the ticket goes to a person
instead. High severity pages on-call; refund requests open a billing case; churn risk notifies the
account manager. Every action carries the number that triggered it.

You can inspect the exact question schema in the UI, flip open the raw response, and compare the
model's answer with the policy's action.

## Why this pattern is useful

The usual way to get a label out of an LLM is to generate JSON and hope. A decision API makes the
answer space smaller than the model's output space. That changes three things:

- **Latency and cost.** Answers are short and output tokens are not charged. A decision is a
  fraction of a cent at current rates, which makes it reasonable to put several in one workflow.
- **Integration.** The result is a number or a label, so thresholds and routing live in normal code.
- **Uncertainty.** You get a distribution, not just a winner. Low confidence becomes a first-class
  branch: send it to a human, not silently to the wrong queue.

The same question shape is used by Jev, Laya, Cloudflare Clef, and OpenAI's Decisions API, so the
architecture is portable even if the endpoint changes.

## Try it

Repo: [link]

The README covers mock mode (no key needed), a live Foundry deployment, the React UI, and a Docker
image. There is also a labeled scorecard script so you can replace my synthetic examples with your
own:

```text
python scorecard.py
```

It reports team accuracy, severity error, precision/recall for each yes/no signal, p95 latency, and
cost per decision. My mock numbers are not model results - run it against your own tickets before
believing any threshold.

## Caveats

- Probabilities are not explanations. Do not show a score and call it a reason.
- Calibration depends on the task. Validate the thresholds on labeled data from your workload.
- The `redact_pii` action is a signal; redaction itself is still your code.
- Do not point a public demo at real customer data.

The broader lesson: not every step in an AI workflow needs a generative model. Some steps need a
fast, bounded judgment. Treating those as a different primitive makes the whole system easier to
reason about.

---

## Short version (social)

Most AI demos generate text. This one makes decisions.

A support-triage demo on the Microsoft Decision API: one call returns a team (`choice`), a severity
(`score`), and three yes/no probabilities. Application policy turns them into routing - and sends
anything below a confidence threshold to a human.

No JSON parsing, no prose, probabilities you can branch on. Repo + write-up: [link]

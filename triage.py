from __future__ import annotations

from typing import Any

from decision_client import DecisionResult

TEAM_OPTIONS = {
    "billing": "Charges, invoices, refunds, subscription payments, or tax details",
    "technical": "Software errors, outages, bugs, integrations, or performance problems",
    "account": "Sign-in, password, profile, workspace settings, or how-to questions",
    "abuse": "Security incidents, account takeover, harassment, or content that must be removed",
}

SEVERITY_LEVELS = ["Cosmetic", "Minor", "Major", "Critical"]

QUESTIONS: dict[str, dict[str, Any]] = {
    "team": {
        "type": "choice",
        "instructions": (
            "Which team should own this customer request? Pick exactly one team based on "
            "the primary problem. Use abuse for security incidents or harmful content even "
            "when the customer also mentions billing or account access."
        ),
        "criteria": TEAM_OPTIONS,
    },
    "severity": {
        "type": "score",
        "instructions": "How severe is the customer impact described in this request?",
        "criteria": SEVERITY_LEVELS,
    },
    "refund_requested": {
        "type": "noul",
        "instructions": "Does the customer ask for money back, a refund, or the reversal of a charge?",
        "criteria": {
            "true": "The customer explicitly asks for money back or a charge to be reversed",
            "false": "The customer makes no request for money back",
        },
    },
    "contains_pii": {
        "type": "noul",
        "instructions": (
            "Does the message contain sensitive personal data such as a national ID number, "
            "payment card number, home address, or passport number?"
        ),
        "criteria": {
            "true": "Sensitive personal data appears in the message",
            "false": "No sensitive personal data appears in the message",
        },
    },
    "churn_risk": {
        "type": "noul",
        "instructions": "Does the customer threaten to cancel, leave, or switch to a competitor?",
        "criteria": {
            "true": "The customer signals they may cancel, leave, or churn",
            "false": "The customer does not signal cancellation or churn",
        },
    },
}

POLICY = {
    "min_team_confidence": 0.60,
    "refund_threshold": 0.65,
    "pii_threshold": 0.50,
    "churn_threshold": 0.65,
    "severity_p1": 2.50,
    "severity_p2": 1.50,
}

DECISION_ORDER = ["team", "severity", "refund_requested", "contains_pii", "churn_risk"]


def _round(value: float) -> float:
    return round(float(value), 4)


def evaluate(result: DecisionResult, ticket: str) -> dict[str, Any]:
    answers = result.answers

    team_answer = answers.get("team")
    team = (team_answer.choice if team_answer else None) or "unknown"
    team_confidence = team_answer.top_probability if team_answer else 0.0

    severity_answer = answers.get("severity")
    severity = severity_answer.score if severity_answer and severity_answer.score is not None else 0.0

    flags: dict[str, float] = {}
    for name in ("refund_requested", "contains_pii", "churn_risk"):
        answer = answers.get(name)
        flags[name] = answer.probability if answer and answer.probability is not None else 0.0

    review_reasons: list[str] = []
    if team_confidence < POLICY["min_team_confidence"]:
        review_reasons.append(
            f"team confidence {team_confidence:.0%} is below {POLICY['min_team_confidence']:.0%}"
        )
    if flags["contains_pii"] >= POLICY["pii_threshold"]:
        review_reasons.append(f"possible sensitive data ({flags['contains_pii']:.0%})")
    if team == "abuse":
        review_reasons.append("security or abuse category")
    review_required = bool(review_reasons)

    if (
        team == "abuse"
        or flags["contains_pii"] >= POLICY["pii_threshold"]
        or severity >= POLICY["severity_p1"]
    ):
        priority = "P1"
    elif severity >= POLICY["severity_p2"] or flags["churn_risk"] >= POLICY["churn_threshold"]:
        priority = "P2"
    else:
        priority = "P3"

    actions: list[dict[str, Any]] = []

    def add(action: str, rank: int, why: str) -> None:
        actions.append({"action": action, "priority": rank, "why": why})

    if team == "abuse":
        add("hold_for_security_review", 1, "the request was classified as a security or abuse case")
    if flags["contains_pii"] >= POLICY["pii_threshold"]:
        add(
            "redact_pii_before_storage",
            1,
            f"sensitive data probability {flags['contains_pii']:.0%}",
        )
    if review_required:
        add("queue_for_human_triage", 1, "; ".join(review_reasons))
    else:
        add(
            f"auto_assign:{team}",
            2,
            f"team {team} selected at {team_confidence:.0%} confidence",
        )
    if team == "billing" and flags["refund_requested"] >= POLICY["refund_threshold"]:
        add(
            "open_refund_case",
            2,
            f"refund request probability {flags['refund_requested']:.0%}",
        )
    if flags["churn_risk"] >= POLICY["churn_threshold"]:
        add(
            "notify_account_manager",
            2,
            f"churn risk probability {flags['churn_risk']:.0%}",
        )
    if severity >= POLICY["severity_p1"]:
        add("page_oncall", 1, f"severity {severity:.2f} of {len(SEVERITY_LEVELS) - 1}")

    actions.sort(key=lambda item: (item["priority"], item["action"]))

    decisions: list[dict[str, Any]] = []
    for name, answer in answers.items():
        item: dict[str, Any] = {
            "name": name,
            "type": answer.type,
            "confidence": _round(answer.top_probability),
        }
        if answer.type == "choice":
            item["value"] = answer.choice
            distribution = answer.probabilities if isinstance(answer.probabilities, dict) else {}
            item["distribution"] = {
                key: _round(value)
                for key, value in sorted(distribution.items(), key=lambda kv: -kv[1])
            }
            item["options"] = TEAM_OPTIONS if name == "team" else {}
        elif answer.type == "score":
            item["value"] = None if answer.score is None else _round(answer.score)
            item["distribution"] = [_round(p) for p in (answer.probabilities or [])]
            item["levels"] = (
                SEVERITY_LEVELS
                if name == "severity"
                else [str(index) for index in range(len(answer.probabilities or []))]
            )
        else:
            probability = answer.probability if answer.probability is not None else 0.0
            item["value"] = _round(probability)
            item["distribution"] = {"yes": _round(probability), "no": _round(1.0 - probability)}
        decisions.append(item)
    decisions.sort(key=lambda item: DECISION_ORDER.index(item["name"]) if item["name"] in DECISION_ORDER else 99)

    return {
        "ticket": ticket,
        "model": result.model,
        "priority": priority,
        "review_required": review_required,
        "review_reasons": review_reasons,
        "routing": {
            "team": team,
            "team_confidence": _round(team_confidence),
            "severity": _round(severity),
            "flags": {key: _round(value) for key, value in flags.items()},
        },
        "actions": actions,
        "decisions": decisions,
        "policy": POLICY,
        "meta": {
            "latency_ms": round(result.latency_ms, 1),
            "input_tokens": result.input_tokens,
            "estimated_cost_usd": result.estimated_cost_usd,
            "mock": result.mock,
        },
    }

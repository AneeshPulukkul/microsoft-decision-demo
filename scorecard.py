from __future__ import annotations

import argparse
import json
import math
import sys
from statistics import median

from config import build_client
from decision_client import DecisionAPIError
from triage import QUESTIONS, SEVERITY_LEVELS, evaluate

LABELED = [
    {
        "text": "I was charged twice for my March invoice and need the duplicate refunded today.",
        "team": "billing",
        "severity": "Major",
        "refund": True,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Your mobile app crashes every time I open the settings screen after the 4.2 update.",
        "team": "technical",
        "severity": "Minor",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Checkout is down for all EU customers since 09:00. Revenue impact is growing.",
        "team": "technical",
        "severity": "Critical",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "I can't sign in after resetting my password. The reset email never arrives.",
        "team": "account",
        "severity": "Major",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Someone posted my home address and phone number in a public review. Please remove it.",
        "team": "abuse",
        "severity": "Critical",
        "refund": False,
        "pii": True,
        "churn": False,
    },
    {
        "text": "How do I export my workspace to CSV?",
        "team": "account",
        "severity": "Cosmetic",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "We're evaluating a competitor because of the repeated outages. Fix this or we cancel at renewal.",
        "team": "technical",
        "severity": "Critical",
        "refund": False,
        "pii": False,
        "churn": True,
    },
    {
        "text": "The invoice PDF shows the wrong VAT number.",
        "team": "billing",
        "severity": "Minor",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "My card ending 4242 was charged but the plan didn't upgrade. Also, please delete my SSN from your records.",
        "team": "billing",
        "severity": "Major",
        "refund": False,
        "pii": True,
        "churn": False,
    },
    {
        "text": "Dashboard loads slowly on Safari, maybe 3-4 seconds.",
        "team": "technical",
        "severity": "Minor",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Please cancel my subscription immediately and refund the annual fee.",
        "team": "billing",
        "severity": "Major",
        "refund": True,
        "pii": False,
        "churn": True,
    },
    {
        "text": "URGENT: production API returning 500 for all requests, we are down.",
        "team": "technical",
        "severity": "Critical",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "I think my account was hacked; there are logins from another country.",
        "team": "abuse",
        "severity": "Critical",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Can you send me a copy of last month's receipt?",
        "team": "billing",
        "severity": "Cosmetic",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "The SSO integration fails with a 403 for our Okta users.",
        "team": "technical",
        "severity": "Major",
        "refund": False,
        "pii": False,
        "churn": False,
    },
    {
        "text": "Your latest release deleted two weeks of our saved reports. This is unacceptable.",
        "team": "technical",
        "severity": "Critical",
        "refund": False,
        "pii": False,
        "churn": True,
    },
]


def binary_metrics(predictions: list[bool], labels: list[bool]) -> dict[str, float | int]:
    tp = sum(1 for p, y in zip(predictions, labels) if p and y)
    fp = sum(1 for p, y in zip(predictions, labels) if p and not y)
    fn = sum(1 for p, y in zip(predictions, labels) if not p and y)
    tn = sum(1 for p, y in zip(predictions, labels) if not p and not y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the triage policy against a small labeled ticket set."
    )
    parser.add_argument("--mock", action="store_true", help="Use the offline deterministic stub.")
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    parser.add_argument("--limit", type=int, default=0, help="Only score the first N tickets.")
    args = parser.parse_args()

    try:
        client = build_client(mock=args.mock)
    except DecisionAPIError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    cases = LABELED[: args.limit] if args.limit > 0 else LABELED
    level_index = {label: index for index, label in enumerate(SEVERITY_LEVELS)}

    team_hits = 0
    severity_exact = 0
    severity_errors: list[float] = []
    flag_predictions: dict[str, list[bool]] = {"refund": [], "pii": [], "churn": []}
    flag_labels: dict[str, list[bool]] = {"refund": [], "pii": [], "churn": []}
    latencies: list[float] = []
    total_cost = 0.0
    review_count = 0
    mock_used = False
    rows: list[dict] = []

    print("LABELED TICKET SCORECARD" + ("  (MOCK)" if args.mock else ""))
    print("=" * 96)

    for index, case in enumerate(cases, start=1):
        try:
            result = client.ask(case["text"], QUESTIONS)
        except DecisionAPIError as exc:
            print(f"Decision API error: {exc}", file=sys.stderr)
            return 1
        assessment = evaluate(result, case["text"])
        routing = assessment["routing"]
        mock_used = mock_used or assessment["meta"]["mock"]

        expected_level = level_index[case["severity"]]
        predicted_level = int(round(routing["severity"]))
        team_ok = routing["team"] == case["team"]
        severity_ok = predicted_level == expected_level
        team_hits += int(team_ok)
        severity_exact += int(severity_ok)
        severity_errors.append(abs(routing["severity"] - expected_level))

        predicted_flags = {
            "refund": routing["flags"]["refund_requested"] >= 0.5,
            "pii": routing["flags"]["contains_pii"] >= 0.5,
            "churn": routing["flags"]["churn_risk"] >= 0.5,
        }
        for key in flag_predictions:
            flag_predictions[key].append(predicted_flags[key])
            flag_labels[key].append(bool(case[key]))
        review_count += int(assessment["review_required"])
        latencies.append(assessment["meta"]["latency_ms"])
        total_cost += assessment["meta"]["estimated_cost_usd"]

        rows.append(
            {
                "index": index,
                "team_ok": team_ok,
                "severity_ok": severity_ok,
                "predicted_team": routing["team"],
                "expected_team": case["team"],
                "predicted_severity": routing["severity"],
                "expected_severity": expected_level,
                "flags": {
                    key: {
                        "probability": routing["flags"][name],
                        "predicted": predicted_flags[key],
                        "expected": bool(case[key]),
                    }
                    for key, name in (
                        ("refund", "refund_requested"),
                        ("pii", "contains_pii"),
                        ("churn", "churn_risk"),
                    )
                },
                "review_required": assessment["review_required"],
                "latency_ms": assessment["meta"]["latency_ms"],
            }
        )

        flag_text = "  ".join(
            f"{key} {routing['flags'][name]:.2f}/{int(bool(case[key]))}"
            for key, name in (
                ("refund", "refund_requested"),
                ("pii", "contains_pii"),
                ("churn", "churn_risk"),
            )
        )
        status = "ok  " if team_ok and severity_ok else "MISS"
        print(
            f"{index:>2}  {status}  team {routing['team']:<10} sev {routing['severity']:.2f}/"
            f"{expected_level}  {flag_text}  {assessment['priority']}"
        )

    count = len(cases)
    binary = {key: binary_metrics(flag_predictions[key], flag_labels[key]) for key in flag_predictions}
    mae = sum(severity_errors) / count if count else 0.0

    print("-" * 96)
    print(f"Team accuracy      {team_hits}/{count} = {team_hits / count:.1%}")
    print(
        f"Severity exact     {severity_exact}/{count} = {severity_exact / count:.1%}"
        f"   MAE {mae:.2f} levels"
    )
    for key in ("refund", "pii", "churn"):
        metric = binary[key]
        print(
            f"{key.capitalize():<18} P={metric['precision']:.2f}  R={metric['recall']:.2f}  "
            f"F1={metric['f1']:.2f}  (tp={metric['tp']} fp={metric['fp']} fn={metric['fn']})"
        )
    print(
        f"Latency            median {median(latencies):.0f} ms   "
        f"p95 {percentile(latencies, 0.95):.0f} ms"
    )
    print(
        f"Cost               ${total_cost:.6f} for {count} decisions   "
        f"avg ${total_cost / count:.8f} each"
    )
    print(f"Policy             {review_count}/{count} sent to human review, {count - review_count} auto-routed")
    if mock_used:
        print("Note               mock mode: numbers exercise the harness, not the hosted model")

    if args.json:
        report = {
            "mock": mock_used,
            "metrics": {
                "team_accuracy": round(team_hits / count, 4),
                "severity_exact": round(severity_exact / count, 4),
                "severity_mae": round(mae, 4),
                "binary": binary,
                "latency_median_ms": round(median(latencies), 1),
                "latency_p95_ms": round(percentile(latencies, 0.95), 1),
                "cost_total_usd": round(total_cost, 8),
                "review_rate": round(review_count / count, 4),
            },
            "cases": rows,
        }
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

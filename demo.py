from __future__ import annotations

import argparse
import json
import sys

from config import build_client
from decision_client import DecisionAPIError
from samples import SAMPLE_TICKETS
from triage import QUESTIONS, SEVERITY_LEVELS, evaluate

BAR_WIDTH = 14
LINE = "=" * 78


def bar(probability: float) -> str:
    filled = max(0, min(BAR_WIDTH, round(probability * BAR_WIDTH)))
    return "#" * filled + "-" * (BAR_WIDTH - filled)


def pct(value: float) -> str:
    return f"{value * 100:5.1f}%"


def render(assessment: dict, show_raw: dict | None = None) -> str:
    lines: list[str] = []
    meta = assessment["meta"]
    routing = assessment["routing"]

    lines.append(LINE)
    lines.append(" DECISION TRIAGE  |  Microsoft-Decision-1.1 on Microsoft Foundry")
    lines.append(LINE)
    lines.append("TICKET")
    for chunk in assessment["ticket"].splitlines() or [""]:
        lines.append(f"  {chunk}")
    lines.append("")

    suffix = "  (MOCK)" if meta["mock"] else ""
    lines.append(f"DECISIONS{suffix}")
    for decision in assessment["decisions"]:
        name = decision["name"]
        kind = decision["type"]
        confidence = decision["confidence"]
        if kind == "choice":
            lines.append(
                f"  {name:<17} choice   {str(decision['value']):<22} p={confidence:.2f}"
            )
            distribution = decision.get("distribution") or {}
            options = decision.get("options") or {}
            for option, probability in distribution.items():
                note = f"  {options[option]}" if option in options else ""
                lines.append(
                    f"      {option:<13} {bar(probability)} {pct(probability)}{note}"
                )
        elif kind == "score":
            score = decision["value"] if decision["value"] is not None else 0.0
            levels = decision.get("levels") or SEVERITY_LEVELS
            lines.append(
                f"  {name:<17} score    {score:.2f} / {max(len(levels) - 1, 0)}"
            )
            for label, probability in zip(levels, decision.get("distribution") or []):
                lines.append(f"      {label:<13} {bar(probability)} {pct(probability)}")
        else:
            value = decision["value"] if decision["value"] is not None else 0.0
            answer = "yes" if value >= 0.5 else "no"
            lines.append(
                f"  {name:<17} noul     {bar(max(value, 1 - value))} {pct(value)} ({answer})"
            )
    lines.append("")

    lines.append("ROUTING")
    lines.append(f"  team      {routing['team']}  ({routing['team_confidence']:.0%} confidence)")
    lines.append(f"  severity  {routing['severity']:.2f} / {len(SEVERITY_LEVELS) - 1}")
    lines.append(f"  priority  {assessment['priority']}")
    if assessment["review_required"]:
        lines.append("  review    yes - " + "; ".join(assessment["review_reasons"]))
    else:
        lines.append("  review    no - every check is above policy threshold")
    lines.append("")

    lines.append("ACTIONS")
    for action in assessment["actions"]:
        lines.append(
            f"  #{action['priority']}  {action['action']:<30} {action['why']}"
        )
    lines.append("")

    lines.append("RUN")
    lines.append(
        f"  {meta['latency_ms']:.0f} ms  |  {meta['input_tokens']} input tokens  |  "
        f"est. ${meta['estimated_cost_usd']:.6f}  |  {assessment['model']}"
    )
    if show_raw is not None:
        lines.append("")
        lines.append("RAW RESPONSE")
        lines.append(json.dumps(show_raw, indent=2))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Microsoft Decision API triage showcase from the terminal."
    )
    parser.add_argument("tickets", nargs="*", help="Ticket text. Omit to run the built-in samples.")
    parser.add_argument("--samples", action="store_true", help="Run all built-in sample tickets.")
    parser.add_argument("--mock", action="store_true", help="Use the offline deterministic stub.")
    parser.add_argument("--json", action="store_true", help="Print the assessment as JSON.")
    parser.add_argument("--raw", action="store_true", help="Include the raw API response.")
    args = parser.parse_args()

    try:
        client = build_client(mock=args.mock)
    except DecisionAPIError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    tickets = list(args.tickets)
    if args.samples or not tickets:
        tickets = [sample["text"] for sample in SAMPLE_TICKETS]

    assessments = []
    raws = []
    for ticket in tickets:
        try:
            result = client.ask(ticket, QUESTIONS)
        except DecisionAPIError as exc:
            print(f"Decision API error: {exc}", file=sys.stderr)
            if exc.body:
                print(exc.body[:800], file=sys.stderr)
            return 1
        assessments.append(evaluate(result, ticket))
        raws.append(result.raw)
        if not args.json:
            print(render(assessments[-1], result.raw if args.raw else None))

    if args.json:
        json.dump(assessments, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

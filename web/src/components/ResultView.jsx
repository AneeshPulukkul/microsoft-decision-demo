import { useEffect, useRef } from "react";
import DecisionCard from "./DecisionCard";
import { money, pct } from "../format";

export default function ResultView({ data }) {
  const ref = useRef(null);
  const result = data.result;

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [data]);

  return (
    <div className="result" ref={ref}>
      <section className={`panel summary ${result.priority.toLowerCase()}`}>
        <div className="summary-top">
          <span className={`chip prio ${result.priority.toLowerCase()}`}>{result.priority}</span>
          <span className="chip">
            team: {result.routing.team} at {pct(result.routing.team_confidence)}
          </span>
          <span className="chip">severity {result.routing.severity.toFixed(2)} / 3</span>
          <span className={`chip ${result.review_required ? "review" : "auto"}`}>
            {result.review_required ? "human review" : "auto-routed"}
          </span>
        </div>
        {result.review_reasons.length > 0 && (
          <ul className="reasons">
            {result.review_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </section>

      <div>
        <h2>Decisions</h2>
        <div className="grid">
          {result.decisions.map((decision) => (
            <DecisionCard key={decision.name} decision={decision} />
          ))}
        </div>
      </div>

      <section className="panel">
        <h2>Action plan</h2>
        <ol className="actions">
          {result.actions.map((action, index) => (
            <li key={`${action.action}-${index}`}>
              <span className="rank">#{action.priority}</span>
              <div className="action-body">
                <code>{action.action}</code>
                <span className="why">{action.why}</span>
              </div>
            </li>
          ))}
        </ol>
        <div className="meta">
          <span>{result.model}</span>
          <span>latency {result.meta.latency_ms.toFixed(0)} ms</span>
          <span>{result.meta.input_tokens} input tokens</span>
          <span>est. {money(result.meta.estimated_cost_usd)}</span>
        </div>
      </section>

      <details className="panel raw">
        <summary>Raw Decision API response</summary>
        <pre>{JSON.stringify(data.raw, null, 2)}</pre>
      </details>
    </div>
  );
}

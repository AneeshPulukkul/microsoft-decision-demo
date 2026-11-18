import { pct } from "../format";

export function PolicyPanel({ policy }) {
  if (!policy) return null;
  return (
    <section className="panel side-panel">
      <h2>Policy, not the model</h2>
      <p className="side-copy">
        The model returns probabilities. These thresholds decide what the application does
        with them.
      </p>
      <dl className="policy">
        <div>
          <dt>Auto-route</dt>
          <dd>team confidence &ge; {pct(policy.min_team_confidence)}</dd>
        </div>
        <div>
          <dt>Human review</dt>
          <dd>
            team below {pct(policy.min_team_confidence)}, PII &ge; {pct(policy.pii_threshold)},
            or abuse
          </dd>
        </div>
        <div>
          <dt>P1</dt>
          <dd>
            severity &ge; {policy.severity_p1.toFixed(1)} or PII / abuse
          </dd>
        </div>
        <div>
          <dt>Refund case</dt>
          <dd>
            refund &ge; {pct(policy.refund_threshold)} and billing
          </dd>
        </div>
        <div>
          <dt>Churn alert</dt>
          <dd>churn &ge; {pct(policy.churn_threshold)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function RequestShape({ questions, deployment }) {
  if (!questions) return null;
  return (
    <details className="panel side-panel raw">
      <summary>Questions sent in every request</summary>
      <p className="side-copy">
        One call, five typed questions. Deployment: <code>{deployment}</code>
      </p>
      <pre>{JSON.stringify({ model: deployment, state: "<ticket text>", questions }, null, 2)}</pre>
    </details>
  );
}

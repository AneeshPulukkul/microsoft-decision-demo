import { LABELS, pct, severityMax } from "../format";

function buildBars(decision) {
  if (decision.type === "choice") {
    const distribution = decision.distribution || {};
    return Object.entries(distribution).map(([label, probability]) => ({
      label,
      probability,
      selected: label === decision.value,
      title: (decision.options || {})[label],
    }));
  }
  if (decision.type === "score") {
    const levels = decision.levels || [];
    const index = Math.max(0, Math.min(levels.length - 1, Math.round(decision.value ?? 0)));
    return levels.map((label, level) => ({
      label,
      probability: (decision.distribution || [])[level] || 0,
      selected: level === index,
    }));
  }
  const probability = decision.value ?? 0;
  return [
    { label: "yes", probability, selected: probability >= 0.5 },
    { label: "no", probability: 1 - probability, selected: probability < 0.5 },
  ];
}

function headline(decision) {
  if (decision.type === "choice") {
    const probability = (decision.distribution || {})[decision.value] ?? decision.confidence;
    return { big: decision.value || "unknown", sub: `${pct(probability)} probability` };
  }
  if (decision.type === "score") {
    const levels = decision.levels || [];
    const value = Number(decision.value ?? 0);
    const index = Math.max(0, Math.min(levels.length - 1, Math.round(value)));
    return { big: `${value.toFixed(2)} / ${severityMax(levels)}`, sub: levels[index] || "" };
  }
  const probability = Number(decision.value ?? 0);
  return { big: pct(probability), sub: probability >= 0.5 ? "yes" : "no" };
}

export default function DecisionCard({ decision }) {
  const { big, sub } = headline(decision);
  const bars = buildBars(decision);

  return (
    <article className="card">
      <div className="card-head">
        <h3>{LABELS[decision.name] || decision.name}</h3>
        <span className="tag">{decision.type}</span>
      </div>
      <div className="card-value">
        <span className="big">{big}</span>
        {sub && <span className="sub">{sub}</span>}
      </div>
      <div className="bars">
        {bars.map((bar) => (
          <div className="bar-row" key={`${decision.name}-${bar.label}`}>
            <span className="bar-label" title={bar.title || undefined}>
              {bar.label}
            </span>
            <div className="track">
              <div
                className={`fill${bar.selected ? " sel" : ""}`}
                style={{ width: `${Math.max(1.5, bar.probability * 100)}%` }}
              />
            </div>
            <span className="bar-pct">{pct(bar.probability)}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

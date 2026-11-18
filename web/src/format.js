export const LABELS = {
  team: "Owning team",
  severity: "Severity",
  refund_requested: "Refund requested",
  contains_pii: "Sensitive data",
  churn_risk: "Churn risk",
};

export function pct(value) {
  const number = (Number(value) * 100).toFixed(1).replace(/\.0$/, "");
  return `${number}%`;
}

export function money(value) {
  return `$${Number(value).toFixed(6)}`;
}

export function severityMax(levels) {
  return Math.max((levels || []).length - 1, 0);
}

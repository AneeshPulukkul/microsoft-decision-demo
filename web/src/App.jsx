import { useCallback, useEffect, useState } from "react";
import TicketForm from "./components/TicketForm";
import ResultView from "./components/ResultView";
import { PolicyPanel, RequestShape } from "./components/SidePanels";
import { decide, getConfig } from "./api";

export default function App() {
  const [config, setConfig] = useState(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    getConfig()
      .then((value) => {
        if (alive) setConfig(value);
      })
      .catch((cause) => {
        if (alive) setError(cause.message);
      });
    return () => {
      alive = false;
    };
  }, []);

  const run = useCallback(
    async (value) => {
      const ticket = (value ?? text).trim();
      if (!ticket || loading) return;
      if (value) setText(ticket);
      setLoading(true);
      setError("");
      try {
        const response = await decide(ticket);
        setData(response);
      } catch (cause) {
        setError(cause.message || String(cause));
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [text, loading]
  );

  return (
    <div className="page">
      <header>
        <div className="eyebrow">Microsoft Foundry &middot; Decision API showcase</div>
        <h1>Decision Triage</h1>
        <p className="lede">
          One request returns a team (<strong>choice</strong>), a severity (<strong>score</strong>)
          and three yes/no signals (<strong>noul</strong>). Application policy turns probabilities
          into routing, with a confidence gate that sends uncertain tickets to a person.
        </p>
        <div className="badges">
          <span className="badge">model: {config?.deployment || "connecting..."}</span>
          {config?.mock && <span className="badge warn">mock mode - no API calls</span>}
        </div>
      </header>

      <main className="layout">
        <div className="col">
          <TicketForm
            text={text}
            onChange={setText}
            onRun={run}
            loading={loading}
            samples={config?.samples}
          />
          {error && (
            <div className="panel error" role="alert">
              {error}
            </div>
          )}
          {data && <ResultView data={data} />}
        </div>
        <aside className="col side">
          <PolicyPanel policy={config?.policy} />
          <RequestShape questions={config?.questions} deployment={config?.deployment} />
        </aside>
      </main>

      <footer>
        Probabilities come from Microsoft-Decision-1.1. Routing, thresholds and actions are
        application policy.
      </footer>
    </div>
  );
}

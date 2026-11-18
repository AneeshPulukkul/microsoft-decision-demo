# Decision Triage

A small, end-to-end showcase for the **Microsoft Decision API** (`Microsoft-Decision-1.1`) on
Microsoft Foundry. One request returns five typed decisions about a support ticket. Application
policy turns the probabilities into routing, an action plan, and a confidence gate that sends
uncertain tickets to a person.

The point is not to generate a reply. The point is to show what changes when a model returns a
`choice`, a `score`, and `noul` (yes/no) probabilities that code can branch on directly.

## What it demonstrates

- Five typed questions in a **single** API call.
- Probabilities used as inputs to policy, not text parsed out of a completion.
- A confidence threshold that separates auto-routing from human review.
- A labeled scorecard for accuracy, severity error, p95 latency, and cost per decision.
- A React UI, a terminal demo, and the same Python client behind both.

## Layout

| Path | Purpose |
| --- | --- |
| `decision_client.py` | Foundry client, URL normalization, retries, typed answer parsing, offline stub |
| `triage.py` | Question schema, thresholds, routing and action policy |
| `demo.py` | Terminal walkthrough |
| `scorecard.py` | Labeled evaluation harness |
| `app.py` | API server and built-UI host |
| `web/` | Vite + React UI |
| `samples.py` | Sample tickets |
| `config.py` | `.env` loading and client factory |

## Requirements

- Python 3.10+
- Node 20+ only if you build the UI

The Python API has **no third-party dependencies** when you use an API key. For Microsoft Entra ID
sign-in instead, install `azure-identity` and sign in with the Azure CLI.

## Quick start (offline)

No key, no deployment, no network calls:

```powershell
python demo.py --mock
python app.py --mock
```

Open http://127.0.0.1:8000. Mock mode is a deterministic stub: it exercises the UI, policy, and
scorecard plumbing, not the hosted model.

## Use the real model

Create a deployment first if you have not already:

```powershell
az cognitiveservices account deployment create `
  --name <ACCOUNT_NAME> `
  --resource-group <RESOURCE_GROUP> `
  --deployment-name microsoft-decision-1.1 `
  --model-name "Microsoft-Decision-1.1" `
  --model-format Microsoft `
  --model-version "1" `
  --sku-name GlobalStandard `
  --sku-capacity 1
```

Then configure and run:

```powershell
Copy-Item .env.example .env
# edit .env: AZURE_ENDPOINT, DEPLOYMENT_NAME, AZURE_API_KEY
python demo.py "Checkout is down for all EU customers since 09:00."
python scorecard.py
python app.py
```

The client accepts these endpoint forms and resolves them to
`<endpoint>/providers/microsoft/v1/systemone`:

- `https://your-resource.cognitiveservices.azure.com/`
- `https://your-resource.services.ai.azure.com/`
- `https://your-resource.services.ai.azure.com/providers/microsoft`

Environment variables override `.env`.

## Web UI

Production (single process serves API and UI):

```powershell
cd web
npm install
npm run build
cd ..
python app.py
```

Development (Vite proxies `/api` to Python):

```powershell
# terminal 1
python app.py --api-only

# terminal 2
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173.

## Docker

```powershell
docker build -t decision-triage .
docker run --rm -p 8000:8000 `
  -e AZURE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/ `
  -e DEPLOYMENT_NAME=microsoft-decision-1.1 `
  -e AZURE_API_KEY=... `
  decision-triage
```

On a PaaS, set `HOST=0.0.0.0` and let `PORT` come from the platform (the Dockerfile already sets
`HOST`).

To split frontend and backend across origins, build with `VITE_API_BASE=https://api.example.com`
and set `CORS_ORIGINS=https://app.example.com`. Same-origin deployment is simpler.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, mock flag, deployment name |
| `GET` | `/api/config` | Deployment, samples, question schema, policy |
| `POST` | `/api/decide` | `{"text": "..."}` -> decisions, action plan, raw response |

Decision responses contain normalized answers plus the raw API payload. Input is capped at 8,000
characters and decisions are rate limited per IP (default 20/minute, `RATE_LIMIT_PER_MIN`, `0`
disables). The rate limiter is in-memory: put a gateway in front for multiple replicas.

## Policy

The model only returns probabilities. These thresholds live in `triage.py` and are visible in the UI.

| Rule | Default |
| --- | --- |
| Auto-route | team confidence >= 60% |
| Human review | team confidence < 60%, PII >= 50%, or `abuse` category |
| P1 | severity >= 2.5, PII >= 50%, or `abuse` |
| Refund case | refund >= 65% and team `billing` |
| Churn alert | churn >= 65% |

Tune the thresholds against your own labeled tickets. The 16 examples in `scorecard.py` are
illustrative, not a benchmark.

## Notes and limits

- Costs are estimates at `$0.042` per million input tokens (`DECISION_PRICE_PER_M_INPUT`); check
  current regional pricing.
- The model returns no rationale. Never present a probability as an explanation.
- The `redact_pii_before_storage` action is a signal, not a redaction implementation.
- Do not send real customer data to a public demo. Use mock mode for public instances or a
  dedicated, monitored deployment with a budget.
- The API also accepts base64 image assets; this demo is text-only to keep the policy path clear.
- `npm audit --omit=dev` is clean. `npm audit` reports a dev-only `picomatch` advisory pulled in by
  Vite's file globbing; no patched release is published yet and it is not shipped to the browser.
- Jev, Laya, Cloudflare Clef, and OpenAI's Decisions API use a similar question shape. The client
  and policy are structured so another provider can be swapped in without rewriting the UI.

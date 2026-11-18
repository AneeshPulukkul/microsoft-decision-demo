from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any

DECISION_PATH = "/providers/microsoft/v1/systemone"
DEFAULT_PRICE_PER_MILLION_INPUT = 0.042
RETRY_STATUS = {429, 500, 502, 503, 504}
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


class DecisionAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class Answer:
    name: str
    type: str
    choice: str | None = None
    probabilities: dict[str, float] | list[float] | None = None
    score: float | None = None
    probability: float | None = None
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def top_probability(self) -> float:
        if self.type == "noul":
            p = self.probability if self.probability is not None else 0.0
            return max(p, 1.0 - p)
        if self.type == "choice" and isinstance(self.probabilities, dict):
            if self.probabilities:
                return max(self.probabilities.values())
        if isinstance(self.probabilities, list) and self.probabilities:
            return max(self.probabilities)
        if self.confidence is not None:
            return self.confidence
        return 0.0


@dataclass
class DecisionResult:
    model: str
    answers: dict[str, Answer]
    usage: dict[str, Any]
    latency_ms: float
    raw: dict[str, Any]
    input_tokens: int
    estimated_cost_usd: float
    mock: bool = False

    def answer(self, name: str) -> Answer | None:
        return self.answers.get(name)


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_prob_map(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        out: dict[str, float] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                item = item.get("probability", item.get("prob", item.get("confidence")))
            number = _to_float(item)
            if number is not None:
                out[str(key)] = number
        return out or None
    if isinstance(value, list):
        out = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            key = (
                item.get("option")
                or item.get("value")
                or item.get("label")
                or item.get("choice")
                or item.get("name")
            )
            number = _to_float(
                item.get("probability", item.get("prob", item.get("confidence")))
            )
            if key is not None and number is not None:
                out[str(key)] = number
        return out or None
    return None


def _as_prob_list(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        try:
            ordered = sorted(value.items(), key=lambda kv: int(kv[0]))
            numbers = [_to_float(v) for _, v in ordered]
        except (TypeError, ValueError):
            numbers = [_to_float(v) for v in value.values()]
        clean = [n for n in numbers if n is not None]
        return clean or None
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            if isinstance(item, dict):
                number = _to_float(item.get("probability", item.get("prob")))
                if number is not None:
                    out.append(number)
            else:
                number = _to_float(item)
                if number is not None:
                    out.append(number)
        return out or None
    return None


def _normalize_answer(name: str, raw: Any) -> Answer:
    if not isinstance(raw, dict):
        raw = {"value": raw}

    kind = str(raw.get("type") or "").lower()
    if kind in ("boolean", "predicate", "bool"):
        kind = "noul"
    if kind not in ("noul", "choice", "score"):
        if raw.get("choice") is not None:
            kind = "choice"
        elif raw.get("score") is not None:
            kind = "score"
        else:
            kind = "noul"

    confidence = _to_float(raw.get("confidence"))

    if kind == "noul":
        probability = _to_float(raw.get("noul"))
        if probability is None:
            probability = _to_float(raw.get("probability"))
        if probability is None:
            probability = _to_float(raw.get("p_true"))
        probabilities = _as_prob_map(raw.get("probabilities"))
        if probability is None and probabilities:
            for key in ("true", "yes", "True", "Yes"):
                if key in probabilities:
                    probability = probabilities[key]
                    break
        if probability is None and confidence is not None:
            probability = confidence
        return Answer(
            name=name,
            type="noul",
            probability=probability,
            confidence=confidence if confidence is not None else probability,
            raw=raw,
        )

    if kind == "choice":
        choice = raw.get("choice")
        if isinstance(choice, dict):
            choice = choice.get("value") or choice.get("key") or choice.get("label")
        choice = None if choice is None else str(choice)
        probabilities = _as_prob_map(raw.get("probabilities"))
        if probabilities is None:
            probabilities = _as_prob_map(raw.get("choices"))
        if confidence is None and probabilities:
            confidence = max(probabilities.values())
        return Answer(
            name=name,
            type="choice",
            choice=choice,
            probabilities=probabilities,
            confidence=confidence,
            raw=raw,
        )

    score = raw.get("score")
    if isinstance(score, dict):
        score = score.get("value", score.get("score", score.get("level")))
    score = _to_float(score)
    probabilities = _as_prob_list(raw.get("probabilities"))
    if probabilities is None:
        probabilities = _as_prob_list(raw.get("levels"))
    if score is None and probabilities:
        score = sum(index * p for index, p in enumerate(probabilities))
    return Answer(
        name=name,
        type="score",
        score=score,
        probabilities=probabilities,
        confidence=confidence,
        raw=raw,
    )


def _normalize_answers(payload: dict[str, Any]) -> dict[str, Answer]:
    raw_answers = payload.get("answers")
    items: list[tuple[str, Any]] = []
    if isinstance(raw_answers, dict):
        items = [(str(k), v) for k, v in raw_answers.items()]
    elif isinstance(raw_answers, list):
        for index, item in enumerate(raw_answers):
            label = item.get("name") if isinstance(item, dict) else None
            items.append((str(label if label is not None else index), item))
    return {name: _normalize_answer(name, raw) for name, raw in items}


def _build_result(
    payload: dict[str, Any],
    latency_ms: float,
    price_per_million_input: float,
    mock: bool = False,
) -> DecisionResult:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = 0
    for key in ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            input_tokens = int(value)
            break
    return DecisionResult(
        model=str(payload.get("model") or ""),
        answers=_normalize_answers(payload),
        usage=usage,
        latency_ms=latency_ms,
        raw=payload,
        input_tokens=input_tokens,
        estimated_cost_usd=input_tokens / 1_000_000 * price_per_million_input,
        mock=mock,
    )


def build_decision_url(endpoint: str) -> str:
    base = (endpoint or "").strip().rstrip("/")
    if not base:
        raise DecisionAPIError("A Foundry endpoint is required.")
    lower = base.lower()
    if lower.endswith(DECISION_PATH):
        return base
    if lower.endswith("/providers/microsoft/v1"):
        return base + "/systemone"
    if lower.endswith("/providers/microsoft"):
        return base + "/v1/systemone"
    return base + DECISION_PATH


class DecisionClient:
    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: str | None = None,
        entra_token: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        price_per_million_input: float = DEFAULT_PRICE_PER_MILLION_INPUT,
    ) -> None:
        self.url = build_decision_url(endpoint)
        self.deployment = deployment
        self.api_key = api_key
        self.entra_token = entra_token
        self.timeout = timeout
        self.max_retries = max_retries
        self.price_per_million_input = price_per_million_input
        self._credential = None
        if not self.api_key and not self.entra_token:
            self._credential = self._make_credential()

    @staticmethod
    def _make_credential():
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise DecisionAPIError(
                "No credential found. Set AZURE_API_KEY, or set AZURE_ENTRA_TOKEN, "
                "or run 'pip install azure-identity' to sign in with Microsoft Entra ID."
            ) from exc
        return DefaultAzureCredential()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
            return headers
        token = self.entra_token
        if not token:
            token = self._credential.get_token(TOKEN_SCOPE).token
        headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post(self, body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        data = json.dumps(body).encode("utf-8")
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                self.url, data=data, headers=self._headers(), method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                latency_ms = (time.perf_counter() - started) * 1000
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise DecisionAPIError("The decision API returned invalid JSON.") from exc
                if not isinstance(payload, dict):
                    raise DecisionAPIError("The decision API returned an unexpected payload.")
                return payload, latency_ms
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                if exc.code in RETRY_STATUS and attempt < self.max_retries:
                    time.sleep(min(8.0, 0.5 * 2**attempt) + random.random() * 0.2)
                    continue
                raise DecisionAPIError(
                    f"The decision API returned HTTP {exc.code} from {self.url}. {detail[:400]}",
                    status=exc.code,
                    body=detail,
                ) from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(8.0, 0.5 * 2**attempt) + random.random() * 0.2)
                    continue
                raise DecisionAPIError(
                    f"Could not reach the decision API at {self.url}: {exc.reason}"
                ) from exc
        raise DecisionAPIError(f"The decision API call failed: {last_error}")

    def ask(
        self,
        state: Any,
        questions: dict[str, Any],
        model: str | None = None,
        assets: dict[str, Any] | None = None,
    ) -> DecisionResult:
        body: dict[str, Any] = {
            "model": model or self.deployment,
            "state": state,
            "questions": questions,
        }
        if assets:
            body["assets"] = assets
        payload, latency_ms = self._post(body)
        return _build_result(payload, latency_ms, self.price_per_million_input)

    @classmethod
    def from_env(cls, **overrides: Any) -> "DecisionClient":
        endpoint = (
            os.environ.get("AZURE_ENDPOINT")
            or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
            or os.environ.get("FOUNDRY_ENDPOINT")
        )
        if not endpoint:
            raise DecisionAPIError(
                "Set AZURE_ENDPOINT to your Foundry resource endpoint, for example "
                "https://your-resource.cognitiveservices.azure.com/"
            )
        deployment = (
            os.environ.get("DEPLOYMENT_NAME")
            or os.environ.get("AZURE_DEPLOYMENT_NAME")
            or "microsoft-decision-1.1"
        )
        options: dict[str, Any] = {
            "endpoint": endpoint,
            "deployment": deployment,
            "api_key": os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_AI_API_KEY"),
            "entra_token": os.environ.get("AZURE_ENTRA_TOKEN"),
            "price_per_million_input": float(
                os.environ.get("DECISION_PRICE_PER_M_INPUT", DEFAULT_PRICE_PER_MILLION_INPUT)
            ),
        }
        options.update(overrides)
        return cls(**options)


class MockDecisionClient:
    def __init__(
        self,
        price_per_million_input: float = DEFAULT_PRICE_PER_MILLION_INPUT,
    ) -> None:
        self.deployment = "microsoft-decision-1.1-mock"
        self.price_per_million_input = price_per_million_input

    def ask(
        self,
        state: Any,
        questions: dict[str, Any],
        model: str | None = None,
        assets: dict[str, Any] | None = None,
    ) -> DecisionResult:
        text = state if isinstance(state, str) else json.dumps(state, sort_keys=True)
        seed = zlib.crc32(text.encode("utf-8"))
        low_confidence = seed % 5 == 0
        confidence = (
            0.42 + (seed % 10) / 100.0
            if low_confidence
            else 0.78 + (seed % 18) / 100.0
        )

        answers: dict[str, Any] = {}
        for name, question in questions.items():
            kind = str(question.get("type", "")).lower()
            if kind == "choice":
                criteria = question.get("criteria") or {}
                keys = list(criteria) if isinstance(criteria, dict) else [str(c) for c in criteria]
                chosen = self._pick_choice(name, text, keys)
                answers[name] = {
                    "type": "choice",
                    "choice": chosen,
                    "confidence": round(confidence, 4),
                    "probabilities": self._distribution(keys, chosen, confidence),
                }
            elif kind == "score":
                levels = question.get("criteria") or []
                index = self._severity(text, len(levels))
                answers[name] = {
                    "type": "score",
                    "score": round(index, 4),
                    "confidence": round(confidence, 4),
                    "probabilities": self._level_distribution(len(levels), index, confidence),
                }
            else:
                probability = self._flag_probability(name, text, seed)
                answers[name] = {
                    "type": "noul",
                    "noul": round(probability, 4),
                    "confidence": round(max(probability, 1.0 - probability), 4),
                }

        tokens = max(60, len(text) // 4 + 140)
        latency_ms = 90 + seed % 260
        payload = {
            "model": "microsoft-decision-1.1-mock",
            "answers": answers,
            "usage": {"input_tokens": tokens, "output_tokens": 6, "total_tokens": tokens + 6},
        }
        time.sleep(latency_ms / 1000)
        return _build_result(payload, latency_ms, self.price_per_million_input, mock=True)

    @staticmethod
    def _distribution(keys: list[str], chosen: str, confidence: float) -> dict[str, float]:
        if not keys:
            return {}
        chosen = chosen if chosen in keys else keys[0]
        others = [k for k in keys if k != chosen]
        result = {chosen: round(confidence, 4)}
        if others:
            share = (1.0 - confidence) / len(others)
            for key in others:
                result[key] = round(share, 4)
        return result

    @staticmethod
    def _level_distribution(count: int, index: float, confidence: float) -> list[float]:
        if count <= 0:
            return []
        level = max(0, min(count - 1, int(round(index))))
        values = [(1.0 - confidence) / max(1, count - 1) for _ in range(count)]
        values[level] = confidence
        return [round(v, 4) for v in values]

    @staticmethod
    def _pick_choice(name: str, text: str, keys: list[str]) -> str:
        lowered = text.lower()
        if name == "team" and keys:
            if "abuse" in keys and any(
                k in lowered
                for k in ("hacked", "breach", "home address", "threat", "abuse", "phishing", "stalking")
            ):
                return "abuse"
            if "billing" in keys and any(
                k in lowered
                for k in ("refund", "charged", "invoice", "receipt", "vat", "billing", "annual fee", "didn't upgrade")
            ):
                return "billing"
            if "account" in keys and any(
                k in lowered
                for k in ("sign in", "login", "password", "export", "csv", "how do i", "reset")
            ):
                return "account"
            if "technical" in keys:
                return "technical"
        return keys[0] if keys else ""

    @staticmethod
    def _severity(text: str, level_count: int) -> float:
        lowered = text.lower()
        if any(
            k in lowered
            for k in (
                "down",
                "outage",
                "critical",
                "urgent",
                "breach",
                "hacked",
                "home address",
                "deleted two weeks",
                "all eu customers",
                "every request",
            )
        ):
            index = 3
        elif any(
            k in lowered
            for k in (
                "crash",
                "sign in",
                "fails",
                "403",
                "cancel",
                "refund",
                "wrong vat",
                "didn't upgrade",
            )
        ):
            index = 2
        elif any(k in lowered for k in ("slow", "wrong", "settings", "warning", "bug", "issue")):
            index = 1
        else:
            index = 0
        return float(min(max(index, 0), max(level_count - 1, 0)))

    @staticmethod
    def _flag_probability(name: str, text: str, seed: int) -> float:
        lowered = text.lower()
        jitter = (seed % 12) / 100.0
        if name == "refund_requested":
            hit = any(k in lowered for k in ("refund", "charged twice", "money back", "return the extra"))
            return min(0.97, 0.9 + jitter) if hit else max(0.02, 0.06 + jitter / 2)
        if name == "contains_pii":
            hit = any(
                k in lowered
                for k in ("ssn", "social security", "card ending", "card number", "home address", "phone number", "passport")
            )
            return min(0.97, 0.88 + jitter) if hit else max(0.02, 0.07 + jitter / 2)
        if name == "churn_risk":
            hit = any(k in lowered for k in ("cancel", "competitor", "churn", "renewal", "lawsuit", "unacceptable"))
            return min(0.97, 0.85 + jitter) if hit else max(0.02, 0.08 + jitter / 2)
        return 0.5

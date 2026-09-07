from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from app.core.settings import ModelRole, Settings

logger = logging.getLogger("nexus.llm")

JSON_REPAIR_SUFFIX = (
    "\n\nYour previous reply was not valid JSON matching the required schema. "
    "Reply with JSON only, no markdown."
)

# Sent verbatim to every provider so a prompt is grounded the same way regardless
# of which model answers it.
GROUNDING_RULES = (
    "You are Nexus, a finance data agent. Follow these rules exactly:\n"
    "1. Use only the data given in this prompt. Never invent column names, table names, "
    "ids, filenames, amounts, dates, or totals.\n"
    "2. Quote values and column names exactly as they appear in the input, character for "
    "character. Do not rename, translate, reformat, or pluralise them.\n"
    "3. Never calculate or estimate a number that is not derivable from the given data. "
    "If a number is not present, leave the field empty or null.\n"
    "4. If the prompt does not contain enough information, return the empty or null value "
    "for that field instead of guessing. An omission is correct; a guess is a defect.\n"
    "5. Do not add commentary, assumptions, caveats, or fields that were not requested.\n"
    "6. Be deterministic: for the same input, always give the same answer."
)

JSON_ONLY_RULES = (
    "Output contract:\n"
    "- Reply with a single JSON object and nothing else. No markdown fences, no prose.\n"
    "- Use only the properties defined in the schema. Do not add extra properties.\n"
    "- Every string must be copied from the input or chosen from the allowed values.\n"
    "- Use null or an empty array rather than a placeholder or invented value."
)


def _json_prompt(prompt: str, schema: dict[str, Any]) -> str:
    return (
        f"{prompt}\n\n{JSON_ONLY_RULES}\n\n"
        f"Respond with JSON only that matches this JSON Schema:\n{json.dumps(schema)}"
    )


def _repair_prompt(base: str, reply: str, error: Exception) -> str:
    """Show the model its own bad reply — repairing blind is what caused drift."""
    return (
        f"{base}{JSON_REPAIR_SUFFIX}\n\nYour previous reply was:\n{reply[:2000]}\n\n"
        f"The error was: {error}"
    )


_GEMINI_SCHEMA_KEYS = ("description", "enum", "format")


def _gemini_response_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Translate a JSON Schema into Gemini's OpenAPI subset, or None if it cannot be.

    Returning None is deliberate: a partly-wrong responseSchema would constrain the
    model incorrectly, which is worse than falling back to the prompted schema.
    """
    if not isinstance(schema, dict):
        return None
    types = _schema_types(schema)
    concrete = [t for t in types if t != "null"]
    if len(concrete) != 1:
        return None
    expected = concrete[0]
    out: dict[str, Any] = {"type": expected.upper()}
    if "null" in types:
        out["nullable"] = True
    for key in _GEMINI_SCHEMA_KEYS:
        if key in schema:
            out[key] = schema[key]
    if expected == "object":
        props = schema.get("properties") or {}
        if not props:
            return None
        converted: dict[str, Any] = {}
        for key, sub in props.items():
            child = _gemini_response_schema(sub)
            if child is None:
                return None
            converted[key] = child
        out["properties"] = converted
        required = [key for key in (schema.get("required") or []) if key in converted]
        if required:
            out["required"] = required
        out["propertyOrdering"] = list(converted)
        return out
    if expected == "array":
        item = _gemini_response_schema(schema.get("items"))
        if item is None:
            return None
        out["items"] = item
        return out
    return out


class LLMError(Exception):
    """Base LLM failure."""


class LLMRetryExhausted(LLMError):
    """Retries exhausted after transient HTTP failures."""


class LLMOutputError(LLMError):
    """Response could not be parsed or failed schema validation."""


class LLMBadRequest(LLMError):
    """The endpoint rejected the request. Carries the body so we can see why."""

    def __init__(self, message: str, status_code: int = 400, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _load_ai_models(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# Everything the endpoint may refuse. `messages` is never negotiable.
_TUNABLE_PARAMS = (
    "temperature",
    "top_p",
    "n",
    "seed",
    "max_tokens",
    "max_completion_tokens",
    "reasoning_effort",
    "response_format",
)


def _rejected_params(body: str, payload: dict[str, Any]) -> set[str]:
    """Read which parameter a 400 objected to, so we can drop just that one."""
    rejected: set[str] = set()
    try:
        error = (json.loads(body) or {}).get("error")
        param = error.get("param") if isinstance(error, dict) else None
        if isinstance(param, str) and param in payload:
            rejected.add(param)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    lowered = body.lower()
    for key in _TUNABLE_PARAMS:
        if key in payload and f"'{key}'" in lowered:
            rejected.add(key)
    return rejected


def _schema_types(schema: dict[str, Any]) -> list[str]:
    expected = schema.get("type")
    if expected is None:
        return []
    if isinstance(expected, list):
        return [str(item) for item in expected]
    return [str(expected)]


def _validate_json_schema(data: Any, schema: dict[str, Any], path: str = "$") -> None:
    types = _schema_types(schema)
    if not types:
        return
    if data is None:
        if "null" in types:
            return
        raise LLMOutputError(f"{path} expected {types[0]}")
    candidates = [t for t in types if t != "null"]
    if len(candidates) > 1:
        last_error: LLMOutputError | None = None
        for candidate in candidates:
            try:
                _validate_json_schema(data, {**schema, "type": candidate}, path)
                return
            except LLMOutputError as exc:
                last_error = exc
        raise last_error or LLMOutputError(f"{path} expected one of {candidates}")
    expected = candidates[0] if candidates else types[0]
    if expected == "object":
        if not isinstance(data, dict):
            raise LLMOutputError(f"{path} expected object, got {type(data).__name__}")
        for key in schema.get("required", []):
            if key not in data:
                raise LLMOutputError(f"{path} missing required property {key!r}")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in data:
                _validate_json_schema(data[key], sub, f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(data, list):
            raise LLMOutputError(f"{path} expected array, got {type(data).__name__}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                _validate_json_schema(item, item_schema, f"{path}[{i}]")
        return
    if expected == "string" and not isinstance(data, str):
        raise LLMOutputError(f"{path} expected string")
    if expected == "number" and (
        not isinstance(data, (int, float)) or isinstance(data, bool)
    ):
        raise LLMOutputError(f"{path} expected number")
    if expected == "integer" and not (
        isinstance(data, int) and not isinstance(data, bool)
    ):
        if isinstance(data, float) and data.is_integer():
            return
        raise LLMOutputError(f"{path} expected integer")
    if expected == "boolean" and not isinstance(data, bool):
        raise LLMOutputError(f"{path} expected boolean")
    if expected == "null" and data is not None:
        raise LLMOutputError(f"{path} expected null")


def _default_for_schema(schema: dict[str, Any] | None) -> Any:
    types = _schema_types(schema or {})
    if "array" in types:
        return []
    if "object" in types:
        return {}
    if "string" in types:
        return ""
    if "integer" in types:
        return 0
    if "number" in types:
        return 0.0
    if "boolean" in types:
        return False
    return None


def _coerce_to_schema(data: Any, schema: dict[str, Any]) -> Any:
    types = _schema_types(schema)
    if not types:
        return data
    if "object" in types and isinstance(data, list):
        required = schema.get("required") or []
        props = schema.get("properties") or {}
        if len(required) == 1 and "array" in _schema_types(props.get(required[0]) or {}):
            data = {required[0]: data}
    if "object" in types:
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return _default_for_schema(schema)
        props = schema.get("properties") or {}
        required = list(schema.get("required") or [])
        out: dict[str, Any] = {}
        keys = set(data) | set(required)
        for key in keys:
            sub = props.get(key) or {}
            if key in data:
                coerced = _coerce_to_schema(data[key], sub) if sub else data[key]
            else:
                coerced = _default_for_schema(sub)
            if coerced is None and key not in required:
                continue
            if coerced is None and key in required and "null" not in _schema_types(sub):
                coerced = _default_for_schema(sub)
            out[key] = coerced
        return out
    if "array" in types:
        if data is None:
            return []
        if not isinstance(data, list):
            data = [data]
        item_schema = schema.get("items")
        if not item_schema:
            return data
        cleaned = []
        for item in data:
            coerced = _coerce_to_schema(item, item_schema)
            if coerced is not None:
                cleaned.append(coerced)
        return cleaned
    if data is None:
        # A nullable field stays null: "unknown" must not become an empty value.
        return None if "null" in types else _default_for_schema(schema)
    if "string" in types and not isinstance(data, str):
        if isinstance(data, (int, float, bool)):
            return str(data)
        return _default_for_schema(schema)
    if "integer" in types and isinstance(data, float) and data.is_integer():
        return int(data)
    if "number" in types and isinstance(data, bool):
        return 0.0
    return data


def _load_json_object(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    parsed = _coerce_to_schema(_extract_json(text), schema)
    _validate_json_schema(parsed, schema)
    if not isinstance(parsed, dict):
        raise LLMOutputError("top-level JSON must be an object")
    return parsed


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = "\n".join(lines[1:])
        if inner.rstrip().endswith("```"):
            inner = inner.rstrip()[:-3]
        stripped = inner.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


class LLMProvider(Protocol):
    async def complete(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float = 0.0,
    ) -> str: ...

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]: ...


class _RetryingMixin:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _request_with_retry(self, send) -> httpx.Response:
        delay = self.settings.llm_retry_base_seconds
        last_exc: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                response = await send()
                if response.status_code in {429, 503, 502, 504}:
                    last_exc = LLMError(
                        f"transient HTTP {response.status_code}: {response.text[:300]}"
                    )
                    if attempt >= self.settings.llm_max_retries:
                        break
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                body = exc.response.text or ""
                if 400 <= exc.response.status_code < 500:
                    raise LLMBadRequest(
                        f"{exc} body={body[:500]}",
                        status_code=exc.response.status_code,
                        body=body,
                    ) from exc
                raise LLMError(f"{exc} body={body[:500]}") from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.settings.llm_max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise LLMRetryExhausted(str(last_exc)) from last_exc

    def _temperature(self, value: float) -> float:
        """One cap for every provider keeps sampling — and drift — comparable."""
        return max(0.0, min(float(value), self.settings.llm_temperature_cap))

    async def _chat(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError

    async def complete(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float = 0.0,
    ) -> str:
        return await self._chat(model_role, prompt, self._temperature(temperature))

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        base = _json_prompt(prompt, schema)
        body = base
        temp = self._temperature(temperature)
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_json_repair_attempts + 1):
            text = ""
            try:
                # _chat is inside the try because an empty completion is an output
                # error too, and one more attempt is cheaper than a dead turn.
                text = await self._chat(model_role, body, temp, schema)
                return _load_json_object(text, schema)
            except (json.JSONDecodeError, LLMOutputError) as exc:
                last_error = exc
                body = _repair_prompt(base, text, exc)
                logger.warning(
                    "%s json repair attempt %s: %s",
                    type(self).__name__,
                    attempt + 1,
                    exc,
                )
        raise LLMOutputError(str(last_error)) from last_error


class GeminiProvider(_RetryingMixin):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings)
        self._client = client

    def _model(self, role: ModelRole) -> str:
        return self.settings.gemini_model_for(role)

    def _generation_config(
        self,
        temperature: float,
        schema: dict[str, Any] | None,
        native_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": temperature,
            # Pinned so Gemini samples as narrowly as the OpenAI-compatible route.
            "topP": 1,
            "topK": 1,
            "candidateCount": 1,
            "maxOutputTokens": self.settings.llm_max_output_tokens,
            "responseMimeType": "application/json" if schema else "text/plain",
        }
        if native_schema:
            config["responseSchema"] = native_schema
        return config

    async def _chat(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        if not self.settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}"
            f"/models/{self._model(model_role)}:generateContent"
        )
        native_schema = (
            _gemini_response_schema(schema)
            if schema and self.settings.llm_native_json_schema
            else None
        )

        async def post(config: dict[str, Any]) -> httpx.Response:
            payload = {
                "systemInstruction": {"parts": [{"text": GROUNDING_RULES}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": config,
            }
            client = self._client or httpx.AsyncClient(timeout=60.0)
            owns = self._client is None
            try:
                return await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "X-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=payload,
                )
            finally:
                if owns:
                    await client.aclose()

        config = self._generation_config(temperature, schema, native_schema)
        try:
            response = await self._request_with_retry(lambda: post(config))
        except LLMError:
            if not native_schema:
                raise
            # Some schemas are rejected by the structured-output endpoint; the
            # prompted schema still applies, so fall back rather than fail.
            logger.warning("gemini rejected responseSchema, retrying prompted-only")
            response = await self._request_with_retry(
                lambda: post(self._generation_config(temperature, schema, None))
            )
        body = response.json()
        try:
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError(f"unexpected Gemini shape: {body!r}"[:500]) from exc


class SAPTokenCache:
    def __init__(self) -> None:
        self.access_token: str | None = None
        self.expires_at: datetime | None = None

    def get(self) -> str | None:
        if not self.access_token or not self.expires_at:
            return None
        if datetime.now(timezone.utc) >= self.expires_at:
            return None
        return self.access_token

    def set(self, token: str, expires_in: int) -> None:
        skew = min(60, max(expires_in // 10, 5))
        self.access_token = token
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - skew)


class SAPAICoreProvider(_RetryingMixin):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        token_cache: SAPTokenCache | None = None,
    ) -> None:
        super().__init__(settings)
        self._client = client
        self.token_cache = token_cache or SAPTokenCache()
        # A parameter a deployment has already refused, so we stop paying for that 400.
        self._refused: dict[str, set[str]] = {}
        # Roles whose deployment turned out to want the reasoning-style token budget.
        self._completion_budget: set[str] = set()

    def _model_name(self, role: ModelRole) -> str:
        return "gpt-4.1"

    def _payload(
        self,
        role: ModelRole,
        prompt: str,
        temperature: float,
        schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        # gpt-4.1 is a chat model: same knobs as Gemini. Never send gpt-5.5 reasoning fields.
        payload: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": GROUNDING_RULES},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": 1,
            "n": 1,
            "seed": self.settings.llm_seed,
            "max_tokens": self.settings.llm_max_output_tokens,
        }
        if schema:
            payload["response_format"] = {"type": "json_object"}
        if role in self._completion_budget and "max_tokens" not in self._refused.get(str(role), set()):
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = self.settings.llm_max_output_tokens
        for key in self._refused.get(str(role), set()):
            payload.pop(key, None)
        return payload

    def _token_url(self) -> str:
        base = self.settings.xsuaa_url.rstrip("/")
        if base.endswith("/oauth/token"):
            return base
        return f"{base}/oauth/token"

    def _chat_url(self, deployment_id: str) -> str:
        api = self.settings.aicore_api_url.rstrip("/")
        return (
            f"{api}/v2/inference/deployments/{deployment_id}/chat/completions"
            f"?api-version={self.settings.aicore_openai_api_version}"
        )

    async def _token(self) -> str:
        cached = self.token_cache.get()
        if cached:
            return cached
        if not (
            self.settings.xsuaa_url
            and self.settings.xsuaa_client_id
            and self.settings.xsuaa_client_secret
        ):
            raise LLMError("SAP AI Core XSUAA credentials are not set")

        async def send() -> httpx.Response:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            owns = self._client is None
            try:
                return await client.post(
                    self._token_url(),
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.xsuaa_client_id,
                        "client_secret": self.settings.xsuaa_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            finally:
                if owns:
                    await client.aclose()

        response = await self._request_with_retry(send)
        body = response.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in") or 3600)
        if not token:
            raise LLMError("XSUAA token response missing access_token")
        self.token_cache.set(token, expires_in)
        return token

    async def _chat(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float,
        schema: dict[str, Any] | None = None,
    ) -> str:
        deployment = self.settings.sap_deployment_for(model_role)
        if not deployment:
            raise LLMError(f"no SAP AI Core deployment id for role {model_role}")
        token = await self._token()
        payload = self._payload(model_role, prompt, temperature, schema)

        async def send() -> httpx.Response:
            client = self._client or httpx.AsyncClient(timeout=180.0)
            owns = self._client is None
            try:
                return await client.post(
                    self._chat_url(deployment),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "AI-Resource-Group": self.settings.aicore_resource_group,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            finally:
                if owns:
                    await client.aclose()

        for _ in range(len(_TUNABLE_PARAMS)):
            try:
                response = await self._request_with_retry(send)
                break
            except LLMBadRequest as exc:
                payload = self._without_rejected(model_role, payload, exc)
        else:
            raise LLMBadRequest(f"SAP AI Core kept rejecting the request for {model_role}")

        body = response.json()
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError(f"unexpected SAP AI Core shape: {body!r}"[:500]) from exc
        if not (content or "").strip():
            # Usually a reasoning model that spent the whole budget thinking; say so,
            # because "empty" reads as a schema bug when it is really a budget one.
            raise LLMOutputError(
                f"empty completion from {self._model_name(model_role) or model_role} "
                f"(finish_reason={choice.get('finish_reason')!r}); "
                "raise LLM_REASONING_MAX_OUTPUT_TOKENS if this repeats"
            )
        return content

    def _without_rejected(
        self,
        role: ModelRole,
        payload: dict[str, Any],
        error: LLMBadRequest,
    ) -> dict[str, Any]:
        """Drop the parameter this deployment refused and remember it for next time."""
        rejected = _rejected_params(error.body, payload)
        identified = bool(rejected)
        if not rejected:
            tunables = [key for key in _TUNABLE_PARAMS if key in payload]
            if not tunables:
                raise error
            # A 400 we cannot attribute: fall back to messages only, which is the
            # payload shape that worked before any sampling knobs were pinned.
            logger.warning(
                "sap_ai_core role %s rejected the request (%s); retrying with messages only",
                role,
                error,
            )
            rejected = set(tunables)
        next_payload = {key: value for key, value in payload.items() if key not in rejected}
        if "max_tokens" in rejected and "max_completion_tokens" not in payload:
            next_payload["max_completion_tokens"] = max(
                self.settings.llm_max_output_tokens,
                self.settings.llm_reasoning_max_output_tokens,
            )
            self._completion_budget.add(str(role))
        if identified:
            # Only a named parameter is remembered; a blind retry stays call-local so
            # an unrelated 400 cannot permanently unpin the sampling.
            self._refused.setdefault(str(role), set()).update(rejected)
            logger.warning(
                "sap_ai_core role %s does not accept %s; dropped for this and later calls",
                role,
                ", ".join(sorted(rejected)),
            )
        return next_payload


def build_llm_provider(
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMProvider:
    settings = settings or Settings()
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings, client=client)
    if settings.llm_provider == "sap_ai_core":
        return SAPAICoreProvider(settings, client=client)
    raise LLMError(f"unknown LLM_PROVIDER {settings.llm_provider!r}")

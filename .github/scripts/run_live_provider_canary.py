from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from agent_evals.live_provider import (
    CanaryDisposition,
    ProviderCanaryLimits,
    ProviderCanaryResponse,
    run_provider_canary,
)

_DEFAULT_URL = "https://api.openai.com/v1/responses"
_PROMPT = "Reply with exactly CANARY_OK"
_EXPECTED = "CANARY_OK"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing required live-canary configuration: {name}")
    return value


def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name, default)
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid numeric live-canary configuration: {name}") from exc


def _int_env(name: str, default: str) -> int:
    raw = os.environ.get(name, default)
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid integer live-canary configuration: {name}") from exc


def _extract_output(data: dict[str, object]) -> str | None:
    direct = data.get("output_text")
    if type(direct) is str:
        return direct
    output = data.get("output")
    if type(output) is not list:
        return None
    texts: list[str] = []
    for item in output:
        if type(item) is not dict:
            continue
        content = item.get("content")
        if type(content) is not list:
            continue
        for part in content:
            if type(part) is not dict:
                continue
            text = part.get("text")
            if type(text) is str:
                texts.append(text)
    return "".join(texts) if texts else None


def _usage_int(data: dict[str, object], key: str) -> int:
    usage = data.get("usage")
    if type(usage) is not dict:
        return 0
    value = usage.get(key, 0)
    return value if type(value) is int and value >= 0 else 0


def main() -> int:
    api_key = _required("OPENAI_API_KEY")
    model = _required("OPENAI_CANARY_MODEL")
    url = os.environ.get("OPENAI_CANARY_URL", _DEFAULT_URL).strip() or _DEFAULT_URL
    output_path = Path(os.environ.get("CANARY_OUTPUT", "live-canary/observation.json"))

    limits = ProviderCanaryLimits(
        max_attempts=_int_env("OPENAI_CANARY_MAX_ATTEMPTS", "3"),
        request_timeout_seconds=_float_env("OPENAI_CANARY_REQUEST_TIMEOUT_SECONDS", "15"),
        wall_clock_seconds=_float_env("OPENAI_CANARY_WALL_CLOCK_SECONDS", "45"),
        max_requests_per_minute=_int_env("OPENAI_CANARY_MAX_REQUESTS_PER_MINUTE", "6"),
        max_input_tokens=_int_env("OPENAI_CANARY_MAX_INPUT_TOKENS", "256"),
        max_output_tokens=_int_env("OPENAI_CANARY_MAX_OUTPUT_TOKENS", "32"),
        input_usd_per_million=_float_env("OPENAI_CANARY_INPUT_USD_PER_MILLION", "0"),
        output_usd_per_million=_float_env("OPENAI_CANARY_OUTPUT_USD_PER_MILLION", "0"),
        max_estimated_cost_usd=_float_env("OPENAI_CANARY_MAX_ESTIMATED_COST_USD", "0.01"),
    )

    def transport(timeout_seconds: float) -> ProviderCanaryResponse:
        payload = json.dumps(
            {
                "model": model,
                "input": _PROMPT,
                "max_output_tokens": limits.max_output_tokens,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agent-evals-live-canary/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    return ProviderCanaryResponse(status_code=502)
                data = json.loads(raw)
                if type(data) is not dict:
                    return ProviderCanaryResponse(status_code=502)
                request_id = response.headers.get("x-request-id")
                model_revision = data.get("model")
                return ProviderCanaryResponse(
                    status_code=response.status,
                    output=_extract_output(data),
                    request_id=request_id,
                    model_revision=model_revision if type(model_revision) is str else None,
                    input_tokens=_usage_int(data, "input_tokens"),
                    output_tokens=_usage_int(data, "output_tokens"),
                )
        except urllib.error.HTTPError as exc:
            retry_after: float | None = None
            retry_header = exc.headers.get("retry-after")
            if retry_header:
                try:
                    retry_after = float(retry_header)
                except ValueError:
                    retry_after = None
            return ProviderCanaryResponse(
                status_code=exc.code,
                request_id=exc.headers.get("x-request-id"),
                retry_after_seconds=retry_after,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("provider request timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("provider request timed out") from exc
            return ProviderCanaryResponse(status_code=503)

    observation = run_provider_canary(
        transport,
        expected_substring=_EXPECTED,
        limits=limits,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(observation.canonical_json() + "\n", encoding="utf-8")
    print(observation.canonical_json())
    return 0 if observation.disposition is CanaryDisposition.OBSERVED else 1


if __name__ == "__main__":
    raise SystemExit(main())

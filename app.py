#!/usr/bin/env python3
import argparse
import os
import sys
import inspect
import contextlib
import io
from typing import Tuple

def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_disabled_instrumentors() -> list[str]:
    raw = os.getenv("OPENLIT_DISABLED_INSTRUMENTORS")
    if raw is None or not raw.strip():
        # Default: disable known-problematic instrumentors.
        return ["agno", "openai"]
    lowered = raw.strip().lower()
    if lowered in {"none", "false", "0"}:
        return []
    disabled: list[str] = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name == "phidata":
            name = "agno"
        if name not in disabled:
            disabled.append(name)
    return disabled


def init_openlit(otlp_endpoint: str):
    # Ensure OTLP exporters are enabled and use HTTP/protobuf for 4318.
    os.environ.setdefault("OTEL_SERVICE_NAME", "llm-monitoring-app")
    os.environ.setdefault("OTEL_TRACES_EXPORTER", "otlp")
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "otlp")
    os.environ.setdefault("OTEL_LOGS_EXPORTER", "otlp")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "http/protobuf")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "http/protobuf")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/protobuf")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_endpoint)

    disabled = parse_disabled_instrumentors()
    if disabled:
        desired = ",".join(disabled)
        current = os.getenv("OPENLIT_DISABLED_INSTRUMENTORS")
        if not current or current.strip().lower() != desired:
            os.environ["OPENLIT_DISABLED_INSTRUMENTORS"] = desired

    try:
        import openlit
    except Exception as exc:
        print(f"OpenLit import failed: {exc}", file=sys.stderr)
        if not env_bool("OPENLIT_ALLOW_FAILURE"):
            raise
        return None

    init_kwargs = {}
    try:
        sig = inspect.signature(openlit.init)
        if "otlp_endpoint" in sig.parameters:
            init_kwargs["otlp_endpoint"] = otlp_endpoint
        if disabled and "disabled_instrumentors" in sig.parameters:
            init_kwargs["disabled_instrumentors"] = disabled
        if "service_name" in sig.parameters:
            init_kwargs["service_name"] = os.getenv("OTEL_SERVICE_NAME", "llm-monitoring-app")
        if "application_name" in sig.parameters:
            init_kwargs["application_name"] = os.getenv("OTEL_SERVICE_NAME", "llm-monitoring-app")
    except (TypeError, ValueError):
        init_kwargs = {}

    def run_init():
        if init_kwargs:
            openlit.init(**init_kwargs)
        else:
            openlit.init()

    try:
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stderr(stderr_buffer):
            run_init()
        init_stderr = stderr_buffer.getvalue()
        if init_stderr:
            filtered = "\n".join(
                line for line in init_stderr.splitlines()
                if "async_agno.py" not in line
            ).strip()
            if filtered:
                print(filtered, file=sys.stderr)
        return openlit
    except Exception as exc:
        message = str(exc)
        if "async_agno.py" in message and "agno" not in disabled:
            try:
                disabled.append("agno")
                os.environ["OPENLIT_DISABLED_INSTRUMENTORS"] = ",".join(disabled)
                retry_kwargs = {}
                try:
                    sig = inspect.signature(openlit.init)
                    if "otlp_endpoint" in sig.parameters:
                        retry_kwargs["otlp_endpoint"] = otlp_endpoint
                    if "disabled_instrumentors" in sig.parameters:
                        retry_kwargs["disabled_instrumentors"] = disabled
                except (TypeError, ValueError):
                    retry_kwargs = {}

                if retry_kwargs:
                    openlit.init(**retry_kwargs)
                else:
                    openlit.init()
                print("OpenLit: disabled agno instrumentor after init error.", file=sys.stderr)
                return openlit
            except Exception as exc2:
                print(f"OpenLit init failed after retry: {exc2}", file=sys.stderr)
        else:
            print(f"OpenLit init failed: {exc}", file=sys.stderr)

        if not env_bool("OPENLIT_ALLOW_FAILURE"):
            raise
        return None


def resolve_provider(provider: str) -> Tuple[str, str, str]:
    if provider == "lmstudio":
        base_url = env_str("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        api_key = env_str("LMSTUDIO_API_KEY", "lm-studio")
        model = env_str("LMSTUDIO_MODEL", "")
    elif provider == "ollama":
        base_url = env_str("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        api_key = env_str("OLLAMA_API_KEY", "ollama")
        model = env_str("OLLAMA_MODEL", "")
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return base_url, api_key, model or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Local LLM call with OpenLit instrumentation.")
    parser.add_argument(
        "--provider",
        choices=["lmstudio", "ollama"],
        default=os.getenv("PROVIDER", "ollama"),
        help="Target runtime (lmstudio or ollama). Defaults to PROVIDER env var or 'ollama'.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("MODEL", ""),
        help="Model name (overrides LMSTUDIO_MODEL or OLLAMA_MODEL).",
    )
    parser.add_argument(
        "--prompt",
        default="Say 'monitoring test' and list two reasons observability matters.",
        help="User prompt to send.",
    )
    parser.add_argument(
        "--system",
        default="You are a concise assistant.",
        help="System prompt.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=256,
        help="Max tokens for the response.",
    )
    args = parser.parse_args()

    base_url, api_key, provider_model = resolve_provider(args.provider)
    model = args.model or provider_model
    if not model:
        print(
            "Model is required. Set --model or MODEL, or set LMSTUDIO_MODEL/OLLAMA_MODEL.",
            file=sys.stderr,
        )
        return 2

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    openlit_mod = init_openlit(otlp_endpoint)
    if openlit_mod:
        print(f"OpenLit initialized (OTLP {otlp_endpoint}).", file=sys.stderr)

    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key)

    def call_model():
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": args.system},
                {"role": "user", "content": args.prompt},
            ],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )

    try:
        if openlit_mod:
            with openlit_mod.start_trace("llm.request") as trace:
                response = call_model()
                try:
                    completion = response.choices[0].message.content or ""
                    trace.set_result(completion)
                except Exception:
                    pass
        else:
            response = call_model()
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    message = response.choices[0].message.content
    print(message)

    if response.usage:
        print("\nusage:", response.usage)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

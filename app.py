#!/usr/bin/env python3
import argparse
import os
import sys
from typing import Tuple

import openlit


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


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
    openlit.init(otlp_endpoint=otlp_endpoint)

    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": args.system},
                {"role": "user", "content": args.prompt},
            ],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
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

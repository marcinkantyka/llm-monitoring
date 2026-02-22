#!/usr/bin/env python3
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

import openlit


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


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = int(round((p / 100.0) * (len(ordered) - 1)))
    return ordered[k]


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test local LLM with OpenLit instrumentation.")
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
        default=env_str(
            "LOADTEST_PROMPT",
            "Say 'monitoring test {i}' and give one reason observability matters.",
        ),
        help="User prompt (supports {i} placeholder).",
    )
    parser.add_argument(
        "--system",
        default=env_str("LOADTEST_SYSTEM", "You are a concise assistant."),
        help="System prompt.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=env_float("LOADTEST_TEMPERATURE", 0.2),
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=env_int("LOADTEST_MAX_TOKENS", 128),
        help="Max tokens for the response.",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=env_int("LOADTEST_REQUESTS", 20),
        help="Total requests to send.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=env_int("LOADTEST_CONCURRENCY", 5),
        help="Parallel request workers.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=env_float("LOADTEST_DELAY", 0.0),
        help="Delay (seconds) between scheduling requests.",
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

    total = max(1, args.requests)
    concurrency = max(1, min(args.concurrency, total))

    latencies: List[float] = []
    failures: List[str] = []

    def run_one(i: int) -> Tuple[Optional[float], Optional[str]]:
        prompt = args.prompt
        if "{i}" in prompt:
            prompt = prompt.format(i=i)

        client = OpenAI(base_url=base_url, api_key=api_key)
        start = time.perf_counter()
        try:
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": args.system},
                    {"role": "user", "content": prompt},
                ],
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            latency = time.perf_counter() - start
            return latency, None
        except Exception as exc:
            latency = time.perf_counter() - start
            return latency, str(exc)

    start_all = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for i in range(total):
            futures.append(executor.submit(run_one, i))
            if args.delay:
                time.sleep(args.delay)

        for future in as_completed(futures):
            latency, error = future.result()
            if error:
                failures.append(error)
            elif latency is not None:
                latencies.append(latency)

    elapsed = time.perf_counter() - start_all

    successes = len(latencies)
    p50 = percentile(latencies, 50) if latencies else 0.0
    p95 = percentile(latencies, 95) if latencies else 0.0
    avg = sum(latencies) / len(latencies) if latencies else 0.0

    print("Load test complete")
    print(f"Requests: {total}")
    print(f"Concurrency: {concurrency}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Successes: {successes}")
    print(f"Failures: {len(failures)}")
    print(f"Latency avg: {avg:.2f}s | p50: {p50:.2f}s | p95: {p95:.2f}s")

    if failures:
        print("\nSample error:")
        print(failures[0])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

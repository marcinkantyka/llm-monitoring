#!/usr/bin/env python3
import argparse
import sys
import time
from typing import List, Tuple

import requests


def fetch_text(url: str, timeout: float = 2.5) -> str:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_metric(text: str, name: str) -> Tuple[bool, str]:
    lines = [line for line in text.splitlines() if line.startswith(name)]
    if not lines:
        return False, f"{name}: missing"
    return True, f"{name}: {lines[0]}"


def list_s3_objects(bucket: str, prefix: str, limit: int) -> Tuple[bool, str]:
    import subprocess

    cmd = [
        sys.executable,
        "s3_inspect.py",
        "list",
        "--bucket",
        bucket,
        "--prefix",
        prefix,
        "--limit",
        str(limit),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, f"s3_inspect failed: {result.stderr.strip() or result.stdout.strip()}"
    output = result.stdout.strip()
    if not output:
        return False, "s3_inspect: no objects"
    first_line = output.splitlines()[0]
    return True, f"s3_inspect: {first_line}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local LLM monitoring stack.")
    parser.add_argument("--collector", default="http://localhost:8888/metrics", help="Collector metrics URL.")
    parser.add_argument("--tempo", default="http://localhost:3200/metrics", help="Tempo metrics URL.")
    parser.add_argument("--bucket", default="llm-telemetry", help="LocalStack bucket name.")
    parser.add_argument("--prefix", default="otel", help="S3 prefix.")
    parser.add_argument("--limit", type=int, default=1, help="S3 list limit.")
    parser.add_argument("--retries", type=int, default=2, help="Retries for metric fetch.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep between retries.")
    args = parser.parse_args()

    checks: List[Tuple[bool, str]] = []

    collector_text = ""
    for attempt in range(args.retries + 1):
        try:
            collector_text = fetch_text(args.collector)
            break
        except Exception as exc:
            if attempt >= args.retries:
                checks.append((False, f"collector metrics fetch failed: {exc}"))
            else:
                time.sleep(args.sleep)

    if collector_text:
        checks.append(extract_metric(collector_text, "otelcol_receiver_accepted_spans_total"))

    tempo_text = ""
    for attempt in range(args.retries + 1):
        try:
            tempo_text = fetch_text(args.tempo)
            break
        except Exception as exc:
            if attempt >= args.retries:
                checks.append((False, f"tempo metrics fetch failed: {exc}"))
            else:
                time.sleep(args.sleep)

    if tempo_text:
        checks.append(extract_metric(tempo_text, "tempo_distributor_spans_received_total"))

    checks.append(list_s3_objects(args.bucket, args.prefix, args.limit))

    ok = all(flag for flag, _ in checks)
    print("VERIFY:", "PASS" if ok else "FAIL")
    for flag, message in checks:
        status = "ok" if flag else "fail"
        print(f"- {status}: {message}")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import boto3

GZIP_MAGIC = b"\x1f\x8b"


def s3_client():
    endpoint_url = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "test")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = int(round((p / 100.0) * (len(ordered) - 1)))
    return ordered[k]


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def duration_ms(start_ns: Optional[int], end_ns: Optional[int]) -> Optional[float]:
    if start_ns is None or end_ns is None:
        return None
    if end_ns < start_ns:
        return None
    return (end_ns - start_ns) / 1_000_000.0


def read_input(input_path: Optional[str], s3_bucket: Optional[str], s3_key: Optional[str]) -> bytes:
    if input_path:
        with open(input_path, "rb") as f:
            return f.read()
    if s3_bucket and s3_key:
        s3 = s3_client()
        resp = s3.get_object(Bucket=s3_bucket, Key=s3_key)
        return resp["Body"].read()
    raise ValueError("Provide --input or --s3-bucket and --s3-key")


def maybe_gunzip(data: bytes, force: bool, hint: str) -> bytes:
    import gzip

    if force or hint.endswith(".gz") or data.startswith(GZIP_MAGIC):
        return gzip.decompress(data)
    return data


def safe_json_loads(data: bytes) -> Optional[Any]:
    try:
        text = data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        return None
    if not text:
        return None
    if text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def attr_list_to_dict(attrs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for item in attrs:
        key = item.get("key")
        val = item.get("value", {}) if isinstance(item, dict) else {}
        if not key:
            continue
        # OTLP JSON value is one of stringValue, intValue, boolValue, doubleValue, bytesValue
        for k in ("stringValue", "intValue", "boolValue", "doubleValue", "bytesValue"):
            if k in val:
                out[key] = val[k]
                break
    return out


def summarize_traces_json(payload: Dict[str, Any], max_samples: int) -> List[str]:
    resource_spans = payload.get("resourceSpans") or []
    total_spans = 0
    services = Counter()
    sample_spans: List[str] = []

    for rs in resource_spans:
        resource = rs.get("resource", {})
        attrs = attr_list_to_dict(resource.get("attributes", []))
        service_name = attrs.get("service.name")
        if service_name:
            services[service_name] += 1

        scope_spans = rs.get("scopeSpans")
        if scope_spans is None:
            scope_spans = rs.get("instrumentationLibrarySpans") or []
        for ss in scope_spans:
            spans = ss.get("spans") or []
            total_spans += len(spans)
            for span in spans:
                name = span.get("name")
                if name and len(sample_spans) < max_samples:
                    sample_spans.append(name)

    summary = [f"Traces: spans={total_spans}, resources={len(resource_spans)}"]
    if services:
        summary.append(f"Services: {', '.join([f'{k}({v})' for k, v in services.most_common(5)])}")
    if sample_spans:
        summary.append(f"Sample spans: {', '.join(sample_spans)}")
    return summary


def collect_span_durations_json(payload: Dict[str, Any]) -> Dict[str, List[float]]:
    durations: Dict[str, List[float]] = {}
    resource_spans = payload.get("resourceSpans") or []

    for rs in resource_spans:
        scope_spans = rs.get("scopeSpans")
        if scope_spans is None:
            scope_spans = rs.get("instrumentationLibrarySpans") or []
        for ss in scope_spans:
            spans = ss.get("spans") or []
            for span in spans:
                name = span.get("name") or "<unknown>"
                start = span.get("startTimeUnixNano") or span.get("start_time_unix_nano")
                end = span.get("endTimeUnixNano") or span.get("end_time_unix_nano")
                start_ns = parse_int(start)
                end_ns = parse_int(end)
                dur_ms = duration_ms(start_ns, end_ns)
                if dur_ms is None:
                    continue
                durations.setdefault(name, []).append(dur_ms)

    return durations


def summarize_logs_json(payload: Dict[str, Any], max_samples: int) -> List[str]:
    resource_logs = payload.get("resourceLogs") or []
    total_logs = 0
    services = Counter()
    sample_bodies: List[str] = []

    for rl in resource_logs:
        resource = rl.get("resource", {})
        attrs = attr_list_to_dict(resource.get("attributes", []))
        service_name = attrs.get("service.name")
        if service_name:
            services[service_name] += 1

        scope_logs = rl.get("scopeLogs") or []
        for sl in scope_logs:
            logs = sl.get("logRecords") or []
            total_logs += len(logs)
            for log in logs:
                body = log.get("body", {})
                if isinstance(body, dict):
                    body = body.get("stringValue") or body.get("intValue") or body.get("boolValue")
                if body and len(sample_bodies) < max_samples:
                    sample_bodies.append(str(body))

    summary = [f"Logs: records={total_logs}, resources={len(resource_logs)}"]
    if services:
        summary.append(f"Services: {', '.join([f'{k}({v})' for k, v in services.most_common(5)])}")
    if sample_bodies:
        summary.append(f"Sample log bodies: {', '.join(sample_bodies)}")
    return summary


def summarize_metrics_json(payload: Dict[str, Any], max_samples: int) -> List[str]:
    resource_metrics = payload.get("resourceMetrics") or []
    total_metrics = 0
    metric_names: List[str] = []

    for rm in resource_metrics:
        scope_metrics = rm.get("scopeMetrics") or []
        for sm in scope_metrics:
            metrics = sm.get("metrics") or []
            total_metrics += len(metrics)
            for metric in metrics:
                name = metric.get("name")
                if name and len(metric_names) < max_samples:
                    metric_names.append(name)

    summary = [f"Metrics: metrics={total_metrics}, resources={len(resource_metrics)}"]
    if metric_names:
        summary.append(f"Sample metrics: {', '.join(metric_names)}")
    return summary


def summarize_json(payload: Any, max_samples: int) -> List[str]:
    if not isinstance(payload, dict):
        return ["JSON payload is not an object; cannot summarize."]

    summaries: List[str] = []
    if payload.get("resourceSpans"):
        summaries.extend(summarize_traces_json(payload, max_samples))
    if payload.get("resourceLogs"):
        summaries.extend(summarize_logs_json(payload, max_samples))
    if payload.get("resourceMetrics"):
        summaries.extend(summarize_metrics_json(payload, max_samples))

    if not summaries:
        summaries.append("No OTLP resourceSpans/resourceLogs/resourceMetrics found in JSON.")
    return summaries


def summarize_top_spans(
    span_durations: Dict[str, List[float]], top_n: int, sort_by: str
) -> List[str]:
    if not span_durations:
        return ["No span durations found for top spans."]

    rows: List[Tuple[str, int, float, float, float, float]] = []
    for name, durs in span_durations.items():
        if not durs:
            continue
        total = sum(durs)
        avg = total / len(durs)
        p95 = percentile(durs, 95)
        max_val = max(durs)
        rows.append((name, len(durs), total, avg, p95, max_val))

    if not rows:
        return ["No span durations found for top spans."]

    sort_index = {"total": 2, "avg": 3, "p95": 4, "max": 5}.get(sort_by, 2)
    rows.sort(key=lambda r: r[sort_index], reverse=True)

    lines = [f"Top spans by {sort_by} duration (ms):"]
    for name, count, total, avg, p95, max_val in rows[:top_n]:
        lines.append(
            f"{name} count={count} total_ms={total:.2f} avg_ms={avg:.2f} "
            f"p95_ms={p95:.2f} max_ms={max_val:.2f}"
        )
    return lines


def try_summarize_protobuf(
    data: bytes, max_samples: int, top_spans: int, top_spans_by: str
) -> Optional[List[str]]:
    try:
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
        from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2
        from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
    except Exception:
        return None

    summaries: List[str] = []

    def extract_service_names(resource) -> Optional[str]:
        names = []
        for attr in getattr(resource, "attributes", []):
            if attr.key == "service.name":
                val = attr.value
                if val.string_value:
                    names.append(val.string_value)
        return ", ".join(names) if names else None

    span_durations: Dict[str, List[float]] = {}

    # Traces
    trace_req = trace_service_pb2.ExportTraceServiceRequest()
    try:
        trace_req.ParseFromString(data)
        if trace_req.resource_spans:
            span_count = 0
            sample_spans: List[str] = []
            services = Counter()
            for rs in trace_req.resource_spans:
                svc = extract_service_names(rs.resource)
                if svc:
                    services[svc] += 1
                for ss in rs.scope_spans:
                    span_count += len(ss.spans)
                    for span in ss.spans:
                        dur_ms = duration_ms(span.start_time_unix_nano, span.end_time_unix_nano)
                        if dur_ms is not None:
                            span_durations.setdefault(span.name or "<unknown>", []).append(dur_ms)
                        if len(sample_spans) < max_samples:
                            sample_spans.append(span.name)
            summaries.append(
                f"Traces: spans={span_count}, resources={len(trace_req.resource_spans)}"
            )
            if services:
                summaries.append(
                    f"Services: {', '.join([f'{k}({v})' for k, v in services.most_common(5)])}"
                )
            if sample_spans:
                summaries.append(f"Sample spans: {', '.join(sample_spans)}")
    except Exception:
        pass

    # Logs
    logs_req = logs_service_pb2.ExportLogsServiceRequest()
    try:
        logs_req.ParseFromString(data)
        if logs_req.resource_logs:
            log_count = 0
            sample_bodies: List[str] = []
            services = Counter()
            for rl in logs_req.resource_logs:
                svc = extract_service_names(rl.resource)
                if svc:
                    services[svc] += 1
                for sl in rl.scope_logs:
                    log_count += len(sl.log_records)
                    for log in sl.log_records:
                        if len(sample_bodies) < max_samples:
                            if log.body.string_value:
                                sample_bodies.append(log.body.string_value)
                            elif log.body.int_value:
                                sample_bodies.append(str(log.body.int_value))
            summaries.append(
                f"Logs: records={log_count}, resources={len(logs_req.resource_logs)}"
            )
            if services:
                summaries.append(
                    f"Services: {', '.join([f'{k}({v})' for k, v in services.most_common(5)])}"
                )
            if sample_bodies:
                summaries.append(f"Sample log bodies: {', '.join(sample_bodies)}")
    except Exception:
        pass

    # Metrics
    metrics_req = metrics_service_pb2.ExportMetricsServiceRequest()
    try:
        metrics_req.ParseFromString(data)
        if metrics_req.resource_metrics:
            metric_count = 0
            sample_metrics: List[str] = []
            for rm in metrics_req.resource_metrics:
                for sm in rm.scope_metrics:
                    metric_count += len(sm.metrics)
                    for metric in sm.metrics:
                        if len(sample_metrics) < max_samples:
                            sample_metrics.append(metric.name)
            summaries.append(
                f"Metrics: metrics={metric_count}, resources={len(metrics_req.resource_metrics)}"
            )
            if sample_metrics:
                summaries.append(f"Sample metrics: {', '.join(sample_metrics)}")
    except Exception:
        pass

    if top_spans > 0:
        summaries.extend(summarize_top_spans(span_durations, top_spans, top_spans_by))

    return summaries if summaries else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize OTLP data stored in LocalStack S3 or local files.")
    parser.add_argument("--input", help="Local file path to OTLP data.")
    parser.add_argument("--s3-bucket", help="S3 bucket name in LocalStack.")
    parser.add_argument("--s3-key", help="S3 key to download from LocalStack.")
    parser.add_argument("--gunzip", action="store_true", help="Decompress gzip before parsing.")
    parser.add_argument("--max-samples", type=int, default=5, help="Max sample names to show.")
    parser.add_argument("--top-spans", type=int, default=0, help="Show top N span durations.")
    parser.add_argument(
        "--top-spans-by",
        choices=["total", "avg", "p95", "max"],
        default="total",
        help="Sort top spans by total/avg/p95/max duration.",
    )
    args = parser.parse_args()

    data = read_input(args.input, args.s3_bucket, args.s3_key)
    hint = args.input or (args.s3_key or "")
    data = maybe_gunzip(data, args.gunzip, hint)

    payload = safe_json_loads(data)
    if payload is not None:
        for line in summarize_json(payload, args.max_samples):
            print(line)
        if args.top_spans > 0:
            durations = collect_span_durations_json(payload)
            for line in summarize_top_spans(durations, args.top_spans, args.top_spans_by):
                print(line)
        return 0

    summaries = try_summarize_protobuf(data, args.max_samples, args.top_spans, args.top_spans_by)
    if summaries:
        for line in summaries:
            print(line)
        return 0

    print("Unable to parse input as OTLP JSON or protobuf.")
    print("If this is protobuf, install opentelemetry-proto:")
    print("  pip install opentelemetry-proto")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

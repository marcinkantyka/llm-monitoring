#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime
from typing import Optional

import boto3


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


def list_buckets() -> int:
    s3 = s3_client()
    resp = s3.list_buckets()
    for bucket in resp.get("Buckets", []):
        created = bucket.get("CreationDate")
        created_str = created.isoformat() if isinstance(created, datetime) else str(created)
        print(f"{bucket['Name']}\t{created_str}")
    return 0


def list_objects(bucket: str, prefix: str, limit: int) -> int:
    s3 = s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            print(f"{obj['LastModified'].isoformat()}\t{obj['Size']}\t{obj['Key']}")
            count += 1
            if limit and count >= limit:
                return 0
    return 0


def head_object(bucket: str, key: str) -> int:
    s3 = s3_client()
    resp = s3.head_object(Bucket=bucket, Key=key)
    print(f"Key: {key}")
    print(f"Size: {resp.get('ContentLength')}")
    print(f"LastModified: {resp.get('LastModified')}")
    print(f"ContentType: {resp.get('ContentType')}")
    print(f"ContentEncoding: {resp.get('ContentEncoding')}")
    return 0


def download_object(bucket: str, key: str, out_path: str, gunzip: bool) -> int:
    import gzip

    s3 = s3_client()
    resp = s3.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    content_encoding = (resp.get("ContentEncoding") or "").lower()

    if gunzip or key.endswith(".gz") or content_encoding == "gzip":
        body = gzip.decompress(body)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(body)

    print(f"Wrote {len(body)} bytes to {out_path}")
    return 0


def latest_object(bucket: str, prefix: str) -> Optional[dict]:
    s3 = s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not latest or obj["LastModified"] > latest["LastModified"]:
                latest = obj
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect LocalStack S3 for OpenTelemetry data.")
    parser.add_argument("--bucket", default="llm-telemetry", help="S3 bucket name.")
    parser.add_argument("--prefix", default="otel", help="Key prefix.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("buckets", help="List buckets")

    list_parser = sub.add_parser("list", help="List objects")
    list_parser.add_argument("--limit", type=int, default=50, help="Max objects to print (0 = no limit).")

    head_parser = sub.add_parser("head", help="Head object")
    head_parser.add_argument("key", help="Object key")

    download_parser = sub.add_parser("download", help="Download object")
    download_parser.add_argument("key", help="Object key")
    download_parser.add_argument("--out", required=True, help="Output path")
    download_parser.add_argument("--gunzip", action="store_true", help="Decompress gzip before writing")

    latest_parser = sub.add_parser("latest", help="Find latest object")
    latest_parser.add_argument("--out", help="Output path to save the latest object")
    latest_parser.add_argument("--gunzip", action="store_true", help="Decompress gzip before writing")

    args = parser.parse_args()

    if args.cmd == "buckets":
        return list_buckets()

    if args.cmd == "list":
        return list_objects(args.bucket, args.prefix, args.limit)

    if args.cmd == "head":
        return head_object(args.bucket, args.key)

    if args.cmd == "download":
        return download_object(args.bucket, args.key, args.out, args.gunzip)

    if args.cmd == "latest":
        obj = latest_object(args.bucket, args.prefix)
        if not obj:
            print("No objects found.")
            return 1
        print(f"Latest: {obj['Key']} (size={obj['Size']}, modified={obj['LastModified'].isoformat()})")
        if args.out:
            return download_object(args.bucket, obj["Key"], args.out, args.gunzip)
        return 0

    print("Unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

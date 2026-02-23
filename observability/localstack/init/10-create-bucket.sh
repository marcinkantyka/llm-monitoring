#!/usr/bin/env sh
set -e

awslocal s3 mb s3://llm-telemetry || true

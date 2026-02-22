# Local LLM Monitoring (OpenLit + LocalStack)

End-to-end local LLM observability with OpenLit (OTLP) and LocalStack S3 storage.

## What This Gives You
- Local model calls (LM Studio or Ollama) captured via OpenLit.
- Traces, logs, and metrics exported through OpenTelemetry Collector.
- Data stored locally in S3 (LocalStack).
- Utilities to list, download, and summarize OTLP data.

## Architecture
- Python app calls a local LLM over the OpenAI-compatible API.
- OpenLit instruments the app and exports OTLP data.
- OTel Collector receives OTLP and writes to LocalStack S3.

## Prerequisites
- Python 3.10+
- Docker (for LocalStack + OTel Collector)
- LM Studio or Ollama running locally with a model available

## Optional: Use an env file
Copy `/Users/marcin/projects/llm-monitoring/.env.example` to `.env` and load it as needed.

Local shell:
```bash
set -a
source /Users/marcin/projects/llm-monitoring/.env
set +a
```

Docker Compose:
```bash
docker compose --env-file /Users/marcin/projects/llm-monitoring/.env up -d
```

## 1) Start LocalStack + OTel Collector
```bash
docker compose up -d

docker compose exec localstack awslocal s3 mb s3://llm-telemetry
```
This also starts Grafana, Tempo, Loki, and Prometheus for visual review.

## 2) Install Python Dependencies (for local runs)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r /Users/marcin/projects/llm-monitoring/requirements.txt
```

## 3) Start Your Local LLM Runtime

LM Studio (OpenAI-compatible base URL `http://localhost:1234/v1`):
```bash
# Option A: start from the LM Studio UI
# Option B: CLI
lms server start --port 1234
```

Ollama (OpenAI-compatible base URL `http://localhost:11434/v1`):
```bash
ollama serve
```

## 4) Run The App (Local Python)
Set the provider and model, then run the app.

LM Studio:
```bash
export PROVIDER=lmstudio
export LMSTUDIO_MODEL=<your-model-id>
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

python /Users/marcin/projects/llm-monitoring/app.py --prompt "Summarize the goal of observability in one sentence."
```

Ollama:
```bash
export PROVIDER=ollama
export OLLAMA_MODEL=<your-model-id>
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

python /Users/marcin/projects/llm-monitoring/app.py --prompt "Summarize the goal of observability in one sentence."
```

Notes:
- Set `MODEL` to override `LMSTUDIO_MODEL` or `OLLAMA_MODEL`.
- `OTEL_SERVICE_NAME` can be set to label your service in telemetry.

## 5) Run The App (Docker)
The app runs in Docker while the LLM runs on the host. On Docker Desktop, use `host.docker.internal` to reach the host runtime.

LM Studio:
```bash
export LMSTUDIO_MODEL=<your-model-id>
docker compose --profile lmstudio up --build app-lmstudio
```

Ollama:
```bash
export OLLAMA_MODEL=<your-model-id>
docker compose --profile ollama up --build app-ollama
```

Linux note:
- If `host.docker.internal` is unavailable, set `LMSTUDIO_BASE_URL` or `OLLAMA_BASE_URL` to your host IP (often `http://172.17.0.1:PORT/v1`), or add a host gateway entry.

## 6) Load Testing

### Local (Python)
```bash
python /Users/marcin/projects/llm-monitoring/load_test.py --requests 50 --concurrency 10
```

Optional env vars (also used by Docker load tests):
`LOADTEST_REQUESTS`, `LOADTEST_CONCURRENCY`, `LOADTEST_DELAY`, `LOADTEST_PROMPT`,
`LOADTEST_SYSTEM`, `LOADTEST_TEMPERATURE`, `LOADTEST_MAX_TOKENS`.

### Docker (On Demand via Profiles)
LM Studio:
```bash
export LMSTUDIO_MODEL=<your-model-id>
docker compose --profile loadtest-lmstudio up --build load-test-lmstudio
```

Ollama:
```bash
export OLLAMA_MODEL=<your-model-id>
docker compose --profile loadtest-ollama up --build load-test-ollama
```

Enable via config:
```bash
export COMPOSE_PROFILES=loadtest-lmstudio
export LMSTUDIO_MODEL=<your-model-id>
docker compose up --build load-test-lmstudio
```

## 7) Inspect Data In LocalStack S3
Data layout (from OTel collector config): `s3://llm-telemetry/otel/YYYY/MM/DD/HH/MM/` with gzipped OTLP payloads.

List objects:
```bash
python /Users/marcin/projects/llm-monitoring/s3_inspect.py list --bucket llm-telemetry --prefix otel --limit 25
```

Find the latest object:
```bash
python /Users/marcin/projects/llm-monitoring/s3_inspect.py latest --bucket llm-telemetry --prefix otel
```

Download the latest object:
```bash
python /Users/marcin/projects/llm-monitoring/s3_inspect.py latest --bucket llm-telemetry --prefix otel --out /Users/marcin/projects/llm-monitoring/out/latest.bin
```

## 8) Summarize OTLP Data
Summarize a local file:
```bash
python /Users/marcin/projects/llm-monitoring/otlp_summarize.py --input /Users/marcin/projects/llm-monitoring/out/latest.bin --gunzip
python /Users/marcin/projects/llm-monitoring/otlp_summarize.py --input /Users/marcin/projects/llm-monitoring/out/latest.bin --gunzip --top-spans 5 --top-spans-by p95
```

Summarize directly from LocalStack:
```bash
python /Users/marcin/projects/llm-monitoring/otlp_summarize.py \
  --s3-bucket llm-telemetry \
  --s3-key otel/2026/02/22/23/00/trace-00000001.gz \
  --gunzip --top-spans 5
```

The summarizer supports OTLP JSON or protobuf (gzipped or plain).

## 9) Grafana Review (Traces, Logs, Metrics)
Open Grafana: [http://localhost:3000](http://localhost:3000)

Default login:
- user: `admin`
- password: `admin`

Explore:
- Traces: use the Tempo data source and search by `service.name` (e.g., `llm-monitoring-demo`).
- Logs: use Loki and filter by labels like `service.name`.
- Metrics: use Prometheus; search for `otelcol_` metrics to verify ingestion.

## Configuration Reference
Common variables:
- `PROVIDER`: `lmstudio` or `ollama`
- `MODEL`: overrides provider-specific model env vars
- `OTEL_EXPORTER_OTLP_ENDPOINT`: typically `http://localhost:4318`
- `OTEL_SERVICE_NAME`: service label for telemetry

Provider-specific:
- `LMSTUDIO_BASE_URL`, `LMSTUDIO_MODEL`, `LMSTUDIO_API_KEY`
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY`

Load test:
- `LOADTEST_REQUESTS`, `LOADTEST_CONCURRENCY`, `LOADTEST_DELAY`
- `LOADTEST_PROMPT`, `LOADTEST_SYSTEM`
- `LOADTEST_TEMPERATURE`, `LOADTEST_MAX_TOKENS`

LocalStack:
- `LOCALSTACK_ENDPOINT` (default `http://localhost:4566`)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`

## Troubleshooting
No data in S3:
1. Ensure the bucket exists: `awslocal s3 mb s3://llm-telemetry`.
2. Check collector logs: `docker compose logs otel-collector`.
3. Verify `OTEL_EXPORTER_OTLP_ENDPOINT` is `http://localhost:4318` (local) or `http://otel-collector:4318` (Docker).

Grafana shows no traces/logs:
1. Confirm the observability stack is running: `docker compose ps`.
2. Ensure collector exporters are configured (see `otel/collector.yaml`).
3. Check collector logs for exporter errors.

Prometheus shows no data:
1. Confirm `otel-collector:8889` is reachable from Prometheus.
2. Verify the collector is running and scraping target appears in Prometheus targets.

Model not found:
- LM Studio: confirm the model ID in the UI and that the server is running.
- Ollama: ensure the model is pulled and running (e.g., `ollama list`).

Docker can’t reach the host LLM:
- Use `host.docker.internal` on Docker Desktop.
- On Linux, set `LMSTUDIO_BASE_URL`/`OLLAMA_BASE_URL` to a reachable host IP.

Summarizer errors:
- If files are gzipped, add `--gunzip`.
- If protobuf parsing fails, ensure `opentelemetry-proto` is installed.

## Files
- `app.py`: minimal client that calls the local model and is instrumented by OpenLit.
- `load_test.py`: concurrency load test to generate telemetry.
- `s3_inspect.py`: helper to list and download objects from LocalStack S3.
- `otlp_summarize.py`: summarize OTLP JSON/protobuf from file or LocalStack.
- `otel/collector.yaml`: OTel Collector config that writes to LocalStack S3.
- `docker-compose.yml`: LocalStack + OTel Collector + app/load-test services.
- `.env.example`: environment variable reference.

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
Copy `./.env.example` to `.env` and load it as needed.

Local shell:
```bash
set -a
source ./.env
set +a
```

Docker Compose:
```bash
docker compose --env-file ./.env up -d
```

## 1) Start LocalStack + OTel Collector
```bash
docker compose up -d
```
This also starts Grafana, Tempo, Loki, and Prometheus for visual review.

## 2) Install Python Dependencies (for local runs)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r ./requirements.txt
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

python ./app.py --prompt "Summarize the goal of observability in one sentence."
```

Ollama:
```bash
export PROVIDER=ollama
export OLLAMA_MODEL=<your-model-id>
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

python ./app.py --prompt "Summarize the goal of observability in one sentence."
```

Notes:
- Set `MODEL` to override `LMSTUDIO_MODEL` or `OLLAMA_MODEL`.
- `OTEL_SERVICE_NAME` can be set to label your service in telemetry.
- By default, the app disables the `agno` and `openai` instrumentors to avoid known OpenLit init/runtime issues.
- To re-enable all instrumentors, set `OPENLIT_DISABLED_INSTRUMENTORS=none`.
- If initialization still fails and you want to proceed without telemetry, set `OPENLIT_ALLOW_FAILURE=1`.
- OpenLit’s OpenAI integration requires OpenAI Python SDK >= 1.92.0.

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
python ./load_test.py --requests 50 --concurrency 10
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
python ./s3_inspect.py list --bucket llm-telemetry --prefix otel --limit 25
```

Find the latest object:
```bash
python ./s3_inspect.py latest --bucket llm-telemetry --prefix otel
```

Download the latest object:
```bash
python ./s3_inspect.py latest --bucket llm-telemetry --prefix otel --out ./out/latest.bin
```

## 8) Summarize OTLP Data
Summarize a local file:
```bash
python ./otlp_summarize.py --input ./out/latest.bin --gunzip
python ./otlp_summarize.py --input ./out/latest.bin --gunzip --top-spans 5 --top-spans-by p95
```

Summarize directly from LocalStack:
```bash
python ./otlp_summarize.py \
  --s3-bucket llm-telemetry \
  --s3-key otel/2026/02/22/23/00/trace-00000001.gz \
  --gunzip --top-spans 5
```

The summarizer supports OTLP JSON or protobuf (gzipped or plain).

## 9) Verify The Stack
Run a quick PASS/FAIL check for collector, Tempo, and S3:
```bash
python ./verify_stack.py
```

## 9) Grafana Review (Traces, Logs, Metrics)
Open Grafana: [http://localhost:3000](http://localhost:3000)

Default login:
- user: `admin`
- password: `admin`

Explore:
- Traces: use the Tempo data source and search by `service.name` (e.g., `llm-monitoring-demo`).
- Logs: use Loki and filter by labels like `service.name`.
- Metrics: use Prometheus; search for `otelcol_` metrics to verify ingestion.

Dashboard:
- A pre-provisioned dashboard called **LLM Monitoring Overview** is available under the **LLM Monitoring** folder.

## Configuration Reference
Common variables:
- `PROVIDER`: `lmstudio` or `ollama`
- `MODEL`: overrides provider-specific model env vars
- `OTEL_EXPORTER_OTLP_ENDPOINT`: typically `http://localhost:4318`
- `OTEL_SERVICE_NAME`: service label for telemetry
- `OPENLIT_DISABLED_INSTRUMENTORS`: comma-separated list to disable instrumentations (default: `agno,openai`)
- `OPENLIT_ALLOW_FAILURE`: set to `1` to allow running if OpenLit cannot initialize

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
1. The bucket is auto-created on LocalStack startup (see `observability/localstack/init/10-create-bucket.sh`).
2. Restart LocalStack to re-run the init script: `docker compose restart localstack`.
3. Check collector logs: `docker compose logs otel-collector`.
4. Verify `OTEL_EXPORTER_OTLP_ENDPOINT` is `http://localhost:4318` (local) or `http://otel-collector:4318` (Docker).

Grafana shows no traces/logs:
1. Confirm the observability stack is running: `docker compose ps`.
2. Ensure collector exporters are configured (see `otel/collector.yaml`).
3. Check collector logs for exporter errors.

Prometheus shows no data:
1. Confirm `otel-collector:8888` (collector internal metrics) is reachable from Prometheus.
2. Verify the collector is running and scraping target appears in Prometheus targets.
3. You can also curl `http://localhost:8888/metrics` directly.

Tempo/Loki/Collector fail to start after config changes:
1. Restart the stack: `docker compose down && docker compose up -d`.
2. If errors persist, check logs:
   - `docker compose logs tempo`
   - `docker compose logs loki`
   - `docker compose logs otel-collector`

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

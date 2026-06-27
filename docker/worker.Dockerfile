# AgentForge Arena — background evaluation worker.
#
# Polls the shared reports/runs.sqlite for queued jobs and runs each unit
# through the FROZEN pipeline (run_once/grade/score_run) via afa_api.worker.
# Adds NO scoring. Same image surface as the API so the kernel/runner import
# path is identical.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.27" \
        "httpx>=0.27" \
        "pydantic>=2.6"

COPY afa_api/ /app/afa_api/
COPY kernel/ /app/kernel/
COPY runner/ /app/runner/
COPY examples/ /app/examples/
COPY tasks/ /app/tasks/

ENV PYTHONPATH=/app:/app/kernel:/app/runner \
    AFA_DB_PATH=/app/reports/runs.sqlite \
    AFA_TASKS_DIR=/app/tasks \
    AFA_OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    AFA_WORKER_POLL_SECONDS=2.0

# Long-running poll loop entrypoint.
CMD ["python", "-m", "afa_api.worker"]

# AgentForge Arena — API service (FastAPI / uvicorn).
#
# Serves the read-only projection + job control plane from the frozen
# kernel/runner. The SPA is served separately by the `web` (nginx) service,
# which reverse-proxies /api here. Trusted local single-user tool — no auth.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime Python deps for the local app (no kernel/runner deps beyond stdlib).
# Pinned to the lower bounds already required by the project.
RUN pip install \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.27" \
        "httpx>=0.27" \
        "pydantic>=2.6"

# The app resolves ROOT from afa_api/db.py's location (-> /app), so the
# repo layout must be mirrored under /app. reports/ and tasks/ are bind- or
# volume-mounted at runtime (see docker-compose.yml).
COPY afa_api/ /app/afa_api/
COPY kernel/ /app/kernel/
COPY runner/ /app/runner/
COPY examples/ /app/examples/
COPY tasks/ /app/tasks/

# kernel + runner are importable when the repo root is on sys.path.
ENV PYTHONPATH=/app:/app/kernel:/app/runner \
    AFA_DB_PATH=/app/reports/runs.sqlite \
    AFA_TASKS_DIR=/app/tasks \
    AFA_OLLAMA_BASE_URL=http://host.docker.internal:11434

EXPOSE 8000

# Bound to all interfaces INSIDE the container only; the host port is bound to
# 127.0.0.1 by docker-compose so nothing is exposed off-box.
CMD ["uvicorn", "afa_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

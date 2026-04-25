FROM python:3.12-slim

# System deps: sqlite CLI for ad-hoc debugging, curl for healthcheck,
# git for uv install of any VCS-pinned deps.
RUN apt-get update && apt-get install -y \
    sqlite3 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv — matches host pin pattern; uv handles the project venv.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Project metadata for dependency resolution.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY api/ ./api/

# Install project + dev deps frozen against uv.lock. ``--frozen`` fails
# loudly if uv.lock drifts from pyproject.toml.
RUN uv sync --frozen

EXPOSE 8000

# Bind to 0.0.0.0 inside the container; docker-compose.yml constrains
# the host-side bind to the Tailscale interface.
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

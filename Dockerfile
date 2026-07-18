FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv directly from the official astral-sh container
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the dependency lock files
COPY pyproject.toml uv.lock ./

# Install dependencies into /app/.venv
# We do this before copying the rest of the application code to leverage Docker layer caching
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application code
COPY . /app

# Install the project itself
RUN uv sync --frozen --no-dev

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

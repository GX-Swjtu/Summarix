FROM python:3.13-slim

ARG PIP_INDEX_URL=
ARG UV_INDEX_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" uv; \
    else \
        pip install --no-cache-dir uv; \
    fi

COPY pyproject.toml uv.lock README.md ./
RUN if [ -n "$UV_INDEX_URL" ]; then \
        UV_INDEX_URL="$UV_INDEX_URL" uv sync --frozen --no-dev; \
    else \
        uv sync --frozen --no-dev; \
    fi

COPY app ./app
COPY main.py ./main.py

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "main.py"]

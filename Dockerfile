# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.11.8
ARG UV_VERSION=0.5.11
ARG FFMPEG_IMAGE=mwader/static-ffmpeg:6.1.1

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin
FROM ${FFMPEG_IMAGE} AS ffmpeg-bin

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=uv-bin /uv /usr/local/bin/uv
WORKDIR /app
COPY .python-version pyproject.toml uv.lock ./
RUN test "$(python -c 'import platform; print(platform.python_version())')" \
         = "$(tr -d '[:space:]' < .python-version)"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

RUN mkdir -p /runtime-libs && \
    ldd /usr/local/bin/python3.11 /usr/local/lib/libpython3.11.so.1.0 \
        /usr/local/lib/python3.11/lib-dynload/*.so \
        $(find /opt/venv -name '*.so*' -type f) 2>/dev/null \
    | awk '{ if ($2=="=>" && $3 ~ /^\//) print $3; \
             else if ($1 ~ /^\// && $1 !~ /:$/) print $1 }' \
    | sort -u \
    | xargs -I{} cp --parents -L {} /runtime-libs/

FROM builder AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-groups --no-editable
COPY tests ./tests
ENV AI_CREATOR_PROFILE=test AI_CREATOR_RUNTIME=ci
RUN /opt/venv/bin/ruff check src tests \
 && /opt/venv/bin/ruff format --check src tests \
 && /opt/venv/bin/mypy src \
 && /opt/venv/bin/pytest -p no:cacheprovider

FROM gcr.io/distroless/base-debian12:nonroot AS runtime
ARG PYTHON_VERSION
LABEL org.opencontainers.image.title="ai-creator-agent" \
      org.opencontainers.image.base.name="distroless/base-debian12" \
      ai.creator.python="${PYTHON_VERSION}"
COPY --from=builder /usr/local /usr/local
COPY --from=builder /runtime-libs/ /
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/.python-version /app/.python-version
COPY --from=ffmpeg-bin /ffmpeg /usr/local/bin/ffmpeg
ENV PATH=/opt/venv/bin:/usr/local/bin \
    VIRTUAL_ENV=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_CREATOR_PROFILE=prod \
    AI_CREATOR_RUNTIME=container \
    AI_CREATOR_DATA_DIR=/data \
    AI_CREATOR_TMP_ROOT=/tmp/ai-creator
WORKDIR /app
USER nonroot
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD ["/opt/venv/bin/python", "-m", "ai_creator_agent.env", "healthcheck"]
ENTRYPOINT ["/opt/venv/bin/python", "-m", "ai_creator_agent.env"]
CMD ["diagnose"]

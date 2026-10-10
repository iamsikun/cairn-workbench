FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node
FROM node AS renderer-dependencies
WORKDIR /renderer
COPY vendor/answer-me-with-html/package.json vendor/answer-me-with-html/package-lock.json ./
RUN npm ci --ignore-scripts
FROM renderer-dependencies AS renderer-build
COPY vendor/answer-me-with-html/src/ src/
COPY vendor/answer-me-with-html/bin/ bin/
COPY vendor/answer-me-with-html/scripts/ scripts/
RUN --network=none node scripts/build-application.mjs /application.mjs

# Reviewed base pinned by digest; build has network, processing never does.
FROM ghcr.io/astral-sh/uv@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS base
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /opt/cairn
ENV UV_COMPILE_BYTECODE=1 UV_NO_PROGRESS=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev
COPY src/ src/
COPY --from=renderer-build /application.mjs src/cairn/presentation/resources/application.mjs
RUN uv sync --locked --no-dev --no-editable
ENV PATH="/opt/cairn/.venv/bin:$PATH"
USER 65532:65532
ENTRYPOINT ["python", "-m", "cairn.adapters.worker"]

FROM base AS development
USER root
RUN uv sync --locked --no-editable
COPY tests/ tests/
COPY scripts/ scripts/
COPY schemas/ schemas/
COPY examples/ examples/
COPY templates/ templates/
USER 65532:65532
ENV RUFF_CACHE_DIR=/tmp/ruff MYPY_CACHE_DIR=/tmp/mypy
ENTRYPOINT []
CMD ["pytest", "-p", "no:cacheprovider", "-m", "not isolation"]

# Acquisition is a public-only build step; the resulting bundle is tested offline.
FROM development AS release
USER root
ARG CAIRN_REVISION
ARG CAIRN_WORKER_IMAGE
RUN python scripts/build_release.py --output /opt/release \
    --revision "$CAIRN_REVISION" --worker-image "$CAIRN_WORKER_IMAGE"
USER 65532:65532
CMD ["python", "scripts/release_trial.py", "/opt/release"]

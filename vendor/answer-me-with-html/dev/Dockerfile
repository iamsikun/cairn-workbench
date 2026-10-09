FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
USER root
COPY node-v20.19.0-linux-arm64 /opt/node20
COPY node-v22.14.0-linux-arm64 /opt/node22
COPY node-v24.0.0-linux-arm64 /opt/node24
ENV PATH="/opt/node22/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-cjk fonts-noto-core espeak-ng ffmpeg git python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dependencies
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
WORKDIR /work
ENV AM_CHROME=/usr/bin/chromium AM_NO_UPDATE_CHECK=1 AM_NO_OPEN=1
USER 65532:65532
ENTRYPOINT []
CMD ["node", "--version"]

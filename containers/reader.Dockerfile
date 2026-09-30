# Build only on the owner workstation; this image is never granted network at inference.
FROM nvidia/cuda:12.8.1-devel-ubuntu24.04@sha256:4b9ed5fa8361736996499f64ecebf25d4ec37ff56e4d11323ccde10aa36e0c43
ARG LLAMA_REVISION=feb9a3d6debb3a8544052b04c84fa1f445fd77f5
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake ninja-build python3 python3-venv libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN git init /build/llama && git -C /build/llama fetch --depth=1 \
    https://github.com/ggml-org/llama.cpp.git "$LLAMA_REVISION" \
    && git -C /build/llama checkout --detach FETCH_HEAD \
    && test "$(git -C /build/llama rev-parse HEAD)" = "$LLAMA_REVISION" \
    && cmake -S /build/llama -B /build/llama/build -G Ninja \
       -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DLLAMA_CURL=OFF \
       -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/llama \
    && cmake --build /build/llama/build --target llama-server llama-quantize -j 4 \
    && mkdir -p /opt/llama/bin /opt/llama/lib \
    && cp /build/llama/build/bin/llama-server /build/llama/build/bin/llama-quantize /opt/llama/bin/ \
    && find /build/llama/build -name '*.so*' -exec cp -P '{}' /opt/llama/lib/ ';'
COPY --from=ghcr.io/astral-sh/uv@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca /usr/local/bin/uv /usr/local/bin/uv
WORKDIR /opt/cairn
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --locked --no-dev --extra reader --no-editable
ENV PATH="/opt/cairn/.venv/bin:/opt/llama/bin:$PATH" LD_LIBRARY_PATH="/opt/llama/lib:$LD_LIBRARY_PATH" \
    PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1
USER 65532:65532
ENTRYPOINT ["python", "-m", "cairn.library.reader_worker"]

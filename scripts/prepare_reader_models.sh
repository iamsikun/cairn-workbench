#!/usr/bin/env bash
# Public acquisition only. Run manually in WSL2, outside all processing containers.
set -euo pipefail
dest="${1:?Choose a new dedicated public model build directory}"
test ! -e "$dest"
mkdir -p "$dest"
model_revision=c202236235762e1c871ad0ccb60c8ee5ba337b9a
llama_revision=feb9a3d6debb3a8544052b04c84fa1f445fd77f5
git init "$dest/llama"
git -C "$dest/llama" fetch --depth=1 https://github.com/ggml-org/llama.cpp.git "$llama_revision"
git -C "$dest/llama" checkout --detach FETCH_HEAD
test "$(git -C "$dest/llama" rev-parse HEAD)" = "$llama_revision"
python3 -m venv "$dest/venv"
"$dest/venv/bin/pip" install 'huggingface-hub==0.36.0' -r "$dest/llama/requirements.txt"
"$dest/venv/bin/hf" download Qwen/Qwen3.5-9B --revision "$model_revision" --local-dir "$dest/weights"
"$dest/venv/bin/python" "$dest/llama/convert_hf_to_gguf.py" "$dest/weights" \
    --outfile "$dest/model-f16.gguf" --outtype f16
"$dest/venv/bin/python" "$dest/llama/convert_hf_to_gguf.py" "$dest/weights" \
    --mmproj --outfile "$dest/mmproj.gguf" --outtype f16
cmake -S "$dest/llama" -B "$dest/llama/build" -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89
cmake --build "$dest/llama/build" --target llama-quantize -j 4
"$dest/llama/build/bin/llama-quantize" "$dest/model-f16.gguf" "$dest/model.gguf" Q8_0
sha256sum "$dest/model.gguf" "$dest/mmproj.gguf" > "$dest/artifact-sha256.txt"
printf 'model_revision=%s\nruntime_revision=%s\nquantization=Q8_0\n' \
    "$model_revision" "$llama_revision" > "$dest/provenance.txt"
printf '%s\n' 'Public model artifacts built. GPU memory, quality, isolation, and owner enrollment remain required.'

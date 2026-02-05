#!/usr/bin/env bash
set -euo pipefail

# Mirrors LLM models (Gemma for Android, Qwen for iOS) to S3.
#
# Usage:
#   ./mirror_llm_models.sh              # mirror all models
#   ./mirror_llm_models.sh android      # mirror only Android (Gemma)
#   ./mirror_llm_models.sh ios          # mirror only iOS (Qwen)
#
# Prereqs:
#   - export HF_TOKEN=...  (token with access to the gated repos)
#   - export AWS_REGION=... (e.g. us-east-1)
#   - install deps: pip install -r requirements.txt
#
# NOTE: Gemma repo is gated on Hugging Face; you must have accepted the conditions.

MODEL="${1:-all}"  # default: mirror everything

# Convenience: load local env file if present (KEY=VALUE or 'export KEY=VALUE').
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON_BIN="python3"
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

BUCKET_ARN="arn:aws:s3:::glycosense-models-v1"
BUCKET_NAME="glycosense-models-v1"
PREFIX_BASE="models/llm"

mirror_android() {
  echo "=== Downloading Gemma 3 1B for Android (MediaPipe) ==="
  local gemma_s3_key="${PREFIX_BASE}/android/gemma3-1b/gemma3-1b-it-int4.task"

  # Check if already uploaded
  if aws s3api head-object --bucket "$BUCKET_NAME" --key "$gemma_s3_key" >/dev/null 2>&1; then
    echo "SKIP: s3://${BUCKET_NAME}/${gemma_s3_key} already exists."
    return
  fi

  local gemma_url="https://huggingface.co/litert-community/Gemma3-1B-IT/resolve/main/gemma3-1b-it-int4.task"
  local gemma_local="gemma3-1b-it-int4.task"

  echo "Downloading ${gemma_url}..."
  curl -L -H "Authorization: Bearer ${HF_TOKEN}" \
    -o "$gemma_local" \
    "$gemma_url"

  if [[ -f "$gemma_local" ]]; then
    echo "Uploading to s3://${BUCKET_NAME}/${gemma_s3_key}..."
    aws s3 cp "$gemma_local" "s3://${BUCKET_NAME}/${gemma_s3_key}" \
      --metadata "hf_repo=litert-community/Gemma3-1B-IT,hf_revision=main"
    rm -f "$gemma_local"
    echo "Gemma model uploaded successfully"
  else
    echo "Failed to download Gemma model" >&2
    exit 1
  fi
}

mirror_ios() {
  echo "=== Mirroring Qwen 2.5 0.5B for iOS (MLX) ==="
  "$PYTHON_BIN" mirror.py \
    --repo "mlx-community/Qwen2.5-0.5B-Instruct-4bit" \
    --bucket "$BUCKET_ARN" \
    --prefix "$PREFIX_BASE/ios/qwen2.5-0.5b/" \
    --zip "qwen2.5-0.5b.zip"
}

case "$MODEL" in
  android)
    mirror_android
    ;;
  ios)
    mirror_ios
    ;;
  all)
    mirror_android
    echo ""
    mirror_ios
    ;;
  *)
    echo "Usage: $0 [android|ios|all]" >&2
    exit 1
    ;;
esac

echo ""
echo "Done."

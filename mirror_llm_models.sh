#!/usr/bin/env bash
set -euo pipefail

# Mirrors LLM models (Gemma for Android, Qwen for iOS) to S3.
#
# Prereqs:
#   - export HF_TOKEN=...  (token with access to the gated repos)
#   - export AWS_REGION=... (e.g. us-east-1)
#   - install deps: pip install -r requirements.txt
#
# NOTE: Gemma repo is gated on Hugging Face; you must have accepted the conditions.

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

# Array of model configurations: name, repo, prefix
# Android: Gemma 3 1B (MediaPipe .task format) - single file, direct download
# iOS: Qwen 2.5 0.5B (MLX format, full repo) - use mirror.py

echo "=== Downloading Gemma 3 1B for Android (MediaPipe) ==="
# Single file - use direct download to avoid downloading entire repo
GEMMA_URL="https://huggingface.co/litert-community/Gemma3-1B-IT/resolve/main/gemma3-1b-it-int4.task"
GEMMA_LOCAL="gemma3-1b-it-int4.task"
GEMMA_S3_KEY="${PREFIX_BASE}/android/gemma3-1b/${GEMMA_LOCAL}"

echo "Downloading $GEMMA_URL..."
curl -L -H "Authorization: Bearer ${HF_TOKEN}" \
  -o "$GEMMA_LOCAL" \
  "$GEMMA_URL"

if [[ -f "$GEMMA_LOCAL" ]]; then
  echo "Uploading to s3://${BUCKET_NAME}/${GEMMA_S3_KEY}..."
  aws s3 cp "$GEMMA_LOCAL" "s3://${BUCKET_NAME}/${GEMMA_S3_KEY}" \
    --metadata "hf_repo=litert-community/Gemma3-1B-IT,hf_revision=main"
  rm -f "$GEMMA_LOCAL"
  echo "✓ Gemma model uploaded successfully"
else
  echo "✗ Failed to download Gemma model"
  exit 1
fi

echo ""
echo "=== Mirroring Qwen 2.5 0.5B for iOS (MLX) ==="
"$PYTHON_BIN" mirror.py \
  --repo "mlx-community/Qwen2.5-0.5B-Instruct-4bit" \
  --bucket "$BUCKET_ARN" \
  --prefix "$PREFIX_BASE/ios/qwen2.5-0.5b/"

echo ""
echo "All LLM models mirrored successfully."

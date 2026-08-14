#!/usr/bin/env bash
set -euo pipefail

# Mirrors Gemma 4 LLM models to S3, one artifact per OS + tier.
#
# Android runs LiteRT-LM and takes the .litertlm file directly.
# iOS runs MLX and takes the whole HF repo zipped up.
#
# Usage:
#   ./mirror_llm_models.sh                  # mirror everything
#   ./mirror_llm_models.sh android          # both Android tiers
#   ./mirror_llm_models.sh ios e4b          # iOS E4B only
#   ./mirror_llm_models.sh all e2b          # both platforms, E2B only
#
# Prereqs:
#   - export HF_TOKEN=...  (token with access to the gated repos)
#   - export AWS_REGION=... (e.g. us-east-1)
#   - install deps: pip install -r requirements.txt
#
# NOTE: the Gemma 4 repos are gated on Hugging Face; the HF_TOKEN account must
# have accepted the Gemma 4 conditions first.

PLATFORM="${1:-all}"  # android | ios | all
TIER="${2:-all}"      # e4b | e2b | all

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

# Scratch space for downloads. These artifacts are 2.6-5.2 GB each, so on a server
# the working set rarely belongs on the root volume. Set MIRROR_WORK_DIR to put
# everything - the Android curl target, the iOS snapshot, and the zip staged by
# mirror.py - on one chosen disk. Defaults to the current directory.
#
# Note HF_HOME alone is not enough: it only affects the iOS path, which goes through
# huggingface_hub. The Android artifacts are fetched with plain curl.
WORK_DIR="${MIRROR_WORK_DIR:-$PWD}"
mkdir -p "$WORK_DIR"

if [[ -n "${MIRROR_WORK_DIR:-}" ]]; then
  # mirror.py stages the zip (uncompressed, so full repo size) in a TemporaryDirectory.
  # Deliberately overrides any inherited TMPDIR: macOS and most shells already set one,
  # so honouring it would silently leave the largest single file on the wrong disk.
  # Set MIRROR_TMPDIR to override.
  export TMPDIR="${MIRROR_TMPDIR:-$WORK_DIR/tmp}"
  mkdir -p "$TMPDIR"
  echo "Using work dir: $WORK_DIR (TMPDIR=$TMPDIR)"
fi

# tier -> Android (LiteRT-LM) source repo and filename
android_repo() {
  case "$1" in
    e4b) echo "litert-community/gemma-4-E4B-it-litert-lm" ;;
    e2b) echo "litert-community/gemma-4-E2B-it-litert-lm" ;;
  esac
}

android_filename() {
  case "$1" in
    e4b) echo "gemma-4-E4B-it.litertlm" ;;
    e2b) echo "gemma-4-E2B-it.litertlm" ;;
  esac
}

# tier -> iOS (MLX) source repo
ios_repo() {
  case "$1" in
    e4b) echo "mlx-community/gemma-4-e4b-it-4bit" ;;
    e2b) echo "mlx-community/gemma-4-e2b-it-4bit" ;;
  esac
}

mirror_android() {
  local tier="$1"
  local repo filename s3_key url local_file

  repo="$(android_repo "$tier")"
  filename="$(android_filename "$tier")"
  s3_key="${PREFIX_BASE}/android/gemma4-${tier}/${filename}"

  echo "=== Android ${tier}: ${repo} ==="

  if aws s3api head-object --bucket "$BUCKET_NAME" --key "$s3_key" >/dev/null 2>&1; then
    echo "SKIP: s3://${BUCKET_NAME}/${s3_key} already exists."
    return
  fi

  url="https://huggingface.co/${repo}/resolve/main/${filename}"
  local_file="${WORK_DIR}/${filename}"

  echo "Downloading ${url}..."
  curl -fL -H "Authorization: Bearer ${HF_TOKEN}" \
    -o "$local_file" \
    "$url"

  if [[ ! -f "$local_file" ]]; then
    echo "Failed to download ${filename}" >&2
    exit 1
  fi

  echo "Uploading to s3://${BUCKET_NAME}/${s3_key}..."
  aws s3 cp "$local_file" "s3://${BUCKET_NAME}/${s3_key}" \
    --metadata "hf_repo=${repo},hf_revision=main"
  rm -f "$local_file"
  echo "Android ${tier} uploaded successfully"
}

mirror_ios() {
  local tier="$1"
  local repo
  repo="$(ios_repo "$tier")"

  echo "=== iOS ${tier}: ${repo} ==="
  # --local-dir keeps the snapshot in WORK_DIR instead of the global HF cache, and
  # is also what lets mirror.py delete it after upload. Without it the snapshot
  # lands in ~/.cache/huggingface and is never cleaned up (~8.7 GB for both tiers).
  "$PYTHON_BIN" mirror.py \
    --repo "$repo" \
    --bucket "$BUCKET_ARN" \
    --prefix "${PREFIX_BASE}/ios/gemma4-${tier}/" \
    --zip "gemma4-${tier}.zip" \
    --local-dir "${WORK_DIR}/snapshot-gemma4-${tier}"
}

case "$TIER" in
  e4b|e2b) TIERS=("$TIER") ;;
  all)     TIERS=(e4b e2b) ;;
  *)
    echo "Usage: $0 [android|ios|all] [e4b|e2b|all]" >&2
    exit 1
    ;;
esac

case "$PLATFORM" in
  android|ios|all) ;;
  *)
    echo "Usage: $0 [android|ios|all] [e4b|e2b|all]" >&2
    exit 1
    ;;
esac

for tier in "${TIERS[@]}"; do
  if [[ "$PLATFORM" == "android" || "$PLATFORM" == "all" ]]; then
    mirror_android "$tier"
    echo ""
  fi
  if [[ "$PLATFORM" == "ios" || "$PLATFORM" == "all" ]]; then
    mirror_ios "$tier"
    echo ""
  fi
done

echo "Done."

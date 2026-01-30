#!/usr/bin/env bash
set -euo pipefail

# Mirrors AI4Bharat IndicConformer language-specific repos to S3.
#
# Prereqs:
#   - export HF_TOKEN=...  (token with access to the gated repos)
#   - export AWS_REGION=... (e.g. us-east-1)
#   - install deps: pip install -r requirements.txt
#
# NOTE: These repos are gated on Hugging Face; you must have accepted the conditions.

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
PREFIX_BASE="models/indicconformer"

# NOTE: macOS ships Bash 3.2 by default, which does not support associative
# arrays (declare -A). Use parallel indexed arrays for portability.
LANGS=(
  hi
  ta
  kn
  te
  ml
)

REPOS=(
  "ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large"
  "ai4bharat/indicconformer_stt_ta_hybrid_ctc_rnnt_large"
  "ai4bharat/indicconformer_stt_kn_hybrid_ctc_rnnt_large"
  "ai4bharat/indicconformer_stt_te_hybrid_ctc_rnnt_large"
  "ai4bharat/indicconformer_stt_ml_hybrid_ctc_rnnt_large"
)

for i in "${!LANGS[@]}"; do
  lang="${LANGS[$i]}"
  repo="${REPOS[$i]}"
  echo "=== Mirroring $lang ($repo) ==="
  "$PYTHON_BIN" mirror.py \
    --repo "$repo" \
    --bucket "$BUCKET_ARN" \
    --prefix "$PREFIX_BASE/$lang/"
done

echo "All done."

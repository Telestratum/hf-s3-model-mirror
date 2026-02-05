# Hugging Face → S3 model mirror

This folder contains a small standalone tool that:

1. Downloads gated Hugging Face model artifacts using a Hugging Face access token (`HF_TOKEN`).
2. Uploads the downloaded files to an AWS S3 bucket/prefix.

It is designed so the **mobile app never needs a Hugging Face token**.

## Security / compliance notes

- **Do not embed** a Hugging Face token in the mobile app.
- Use a **service account** token (or your personal token temporarily) on a backend job.
- Treat `HF_TOKEN` as a secret. Prefer a secrets manager.
- If you previously pasted a token into chat or code, **revoke/rotate it** in Hugging Face.
- Model license and gated-access conditions still apply to mirroring/redistribution.

## Requirements

- Python 3.10+
- AWS credentials with permissions to upload to S3 (example minimal IAM below)

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

Required:

- `HF_TOKEN` – Hugging Face access token with access to the gated model
- `AWS_REGION` – e.g. `us-east-1`

AWS auth (one of these standard methods):

- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ optional `AWS_SESSION_TOKEN`), or
- EC2/ECS task role, or
- `aws sso login` + configured profile

## Usage

### Mirror a whole model repo to S3

```bash
export HF_TOKEN="..."
export AWS_REGION="us-east-1"

python3 mirror.py \
  --repo ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large \
  --bucket your-bucket \
  --prefix models/indicconformer/hi/
```

### Mirror a specific filename pattern only

```bash
python3 mirror.py \
  --repo ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large \
  --include "*.nemo" \
  --bucket your-bucket \
  --prefix models/indicconformer/hi/
```

### Mirror as a zip archive (single file upload)

Instead of uploading individual files, bundle them into a zip and upload that:

```bash
python3 mirror.py \
  --repo mlx-community/Qwen2.5-0.5B-Instruct-4bit \
  --bucket your-bucket \
  --prefix models/llm/ios/qwen2.5-0.5b/ \
  --zip "qwen2.5-0.5b.zip"
```

This uploads a single `<prefix>/qwen2.5-0.5b.zip` to S3 instead of many individual files.

### Skip existing files / force re-upload

By default, `mirror.py` checks S3 before uploading and skips files that already exist. Use `--force` to re-upload regardless:

```bash
python3 mirror.py \
  --repo mlx-community/Qwen2.5-0.5B-Instruct-4bit \
  --bucket your-bucket \
  --prefix models/llm/ios/qwen2.5-0.5b/ \
  --zip "qwen2.5-0.5b.zip" \
  --force
```

### Dry run (prints what would be uploaded)

```bash
python3 mirror.py \
  --repo ai4bharat/indicconformer_stt_hi_hybrid_ctc_rnnt_large \
  --bucket your-bucket \
  --prefix models/indicconformer/hi/ \
  --dry-run
```

### Mirror LLM models (Android + iOS)

The `mirror_llm_models.sh` script handles both Android (Gemma) and iOS (Qwen) models:

```bash
./mirror_llm_models.sh              # mirror all models
./mirror_llm_models.sh android      # Gemma for Android only
./mirror_llm_models.sh ios          # Qwen for iOS only
```

Both paths skip the download/upload if the target already exists in S3.

## Minimal IAM policy example

Scope this down to your bucket/prefix.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:AbortMultipartUpload",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR_BUCKET_NAME",
        "arn:aws:s3:::YOUR_BUCKET_NAME/models/indicconformer/*"
      ]
    }
  ]
}
```

## Notes on `--bucket`

`--bucket` accepts any of:

- Bucket name: `glycosense-models-v1`
- S3 URL: `s3://glycosense-models-v1`
- ARN: `arn:aws:s3:::glycosense-models-v1`

## Output layout recommendation

**Speech models** – one prefix per locale:

- `s3://<bucket>/models/indicconformer/hi/`
- `s3://<bucket>/models/indicconformer/ta/`
- `s3://<bucket>/models/indicconformer/kn/`
- `s3://<bucket>/models/indicconformer/te/`
- `s3://<bucket>/models/indicconformer/ml/`

**LLM models** – one file per OS/model:

- `s3://<bucket>/models/llm/android/gemma3-1b/gemma3-1b-it-int4.task`
- `s3://<bucket>/models/llm/ios/qwen2.5-0.5b/qwen2.5-0.5b.zip`

This keeps the mobile-side mapping trivial.

## Serving the models to mobile clients (recommended)

Keep the S3 bucket/prefix private and have your backend mint short-lived pre-signed S3 URLs.

- Example FastAPI service: `presign_api` (see `presign_api/README.md`)
- Mobile app flow: call backend → receive URL → download from S3 (no AWS keys on device)

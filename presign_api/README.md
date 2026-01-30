# FastAPI pre-signed URL service

This is a minimal FastAPI app that returns short-lived S3 pre-signed URLs for downloading the mirrored model artifacts.

## Why

- Keep the S3 bucket private.
- Never ship AWS credentials to the mobile app.
- Your backend uses its IAM role to mint pre-signed URLs.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r presign_api/requirements.txt

export AWS_REGION=us-east-1
export AWS_PROFILE=your-profile   # optional
export X_API_KEY=change-me        # optional (see env vars below)

uvicorn presign_api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Environment variables

- `S3_BUCKET` (default: `glycosense-models-v1`)
- `S3_PREFIX_BASE` (default: `models/indicconformer`)
- `PRESIGN_TTL_SECONDS` (default: `900`)
- `API_KEY` (default: empty = auth disabled)

If `API_KEY` is set, clients must pass header `X-API-Key: <value>`.

## Endpoint

- `GET /v1/models` lists available `lang` values and S3 keys
- `GET /v1/models/{lang}` returns a pre-signed URL, where `lang` is one of: `hi`, `ta`, `kn`, `te`, `ml`

Response includes `url` and `expires_at`.

## Deploy on EC2

Best practice: attach an instance profile/role with permission:

- `s3:GetObject` on `arn:aws:s3:::<bucket>/models/indicconformer/*`

Then you do not need static access keys on the server.

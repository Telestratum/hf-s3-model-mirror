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
  --repo mlx-community/gemma-4-e4b-it-4bit \
  --bucket your-bucket \
  --prefix models/llm/ios/gemma4-e4b/ \
  --zip "gemma4-e4b.zip"
```

This uploads a single `<prefix>/gemma4-e4b.zip` to S3 instead of many individual files.

### Skip existing files / force re-upload

By default, `mirror.py` checks S3 before uploading and skips files that already exist. Use `--force` to re-upload regardless:

```bash
python3 mirror.py \
  --repo mlx-community/gemma-4-e4b-it-4bit \
  --bucket your-bucket \
  --prefix models/llm/ios/gemma4-e4b/ \
  --zip "gemma4-e4b.zip" \
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

The `mirror_llm_models.sh` script handles Gemma 4 for both platforms, in two size tiers.
Android takes the LiteRT-LM `.litertlm` file directly; iOS takes the MLX repo zipped.

```bash
./mirror_llm_models.sh                  # mirror everything (4 artifacts)
./mirror_llm_models.sh android          # both Android tiers
./mirror_llm_models.sh ios e4b          # iOS E4B only
./mirror_llm_models.sh all e2b          # both platforms, E2B only
```

Both paths skip the download/upload if the target already exists in S3.

The Gemma 4 source repos are **gated** — the `HF_TOKEN` account must have accepted the
Gemma 4 conditions on Hugging Face before these will download.

## Running the LLM mirror on EC2 (recommended)

The LLM job moves ~15 GB down from Hugging Face and ~15 GB back up to S3. Run it on an EC2
instance **in the same region as the bucket** (`ap-south-1`): the upload then goes over
AWS's internal network instead of a home uplink, and no long-lived AWS keys have to leave
the account.

### What to copy

`mirror.py`, `mirror_llm_models.sh`, `requirements.txt`, and `.env`. That is not quite
enough on its own — see the setup below.

Do **not** copy `.venv`: it contains host-specific binaries and will not run on the
instance.

### Instance setup

```bash
# aws CLI — the script shells out to `aws s3api head-object` and `aws s3 cp`.
# Preinstalled on Amazon Linux 2023; on Ubuntu: sudo snap install aws-cli --classic
aws --version

# Python 3.10+ venv. A venv is effectively mandatory on AL2023 / Ubuntu 24.04,
# where PEP 668 blocks pip installs into the system interpreter.
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The script picks up `.venv/bin/python` automatically if it exists, else falls back to
`python3`.

### Disk

Budget **40 GB**. Peak usage is ~10 GB (an iOS snapshot plus its uncompressed zip), but the
artifacts are large enough that headroom matters.

Set `MIRROR_WORK_DIR` to keep the whole working set off the root volume:

```bash
export MIRROR_WORK_DIR=/data/mirror
./mirror_llm_models.sh all
```

That one variable covers all three consumers:

| What | Where it goes |
|---|---|
| Android `.litertlm` (curl target) | `$MIRROR_WORK_DIR/` |
| iOS HF snapshot | `$MIRROR_WORK_DIR/snapshot-gemma4-<tier>/` |
| iOS zip staging | `$MIRROR_WORK_DIR/tmp/` |

Two things worth knowing about why one variable was needed:

- **`HF_HOME` is not sufficient.** It only affects the iOS path, which goes through
  `huggingface_hub`. The Android artifacts are fetched with a plain `curl -o`, which writes
  to the current directory regardless.
- **Setting `MIRROR_WORK_DIR` also stops the cache leak.** It makes the script pass
  `--local-dir` to `mirror.py`, which is the only condition under which `mirror.py` deletes
  the snapshot after upload. Without it the snapshot lands in `~/.cache/huggingface` and is
  never cleaned — about **8.7 GB left behind** across the two iOS tiers.

`MIRROR_WORK_DIR` deliberately overrides any inherited `TMPDIR`, since most shells already
set one and honouring it would leave the single largest file (the uncompressed zip, ~5.15 GB
for E4B) on the wrong disk. Set `MIRROR_TMPDIR` if you need the staging area elsewhere.

### Credentials

`.env` carries only `HF_TOKEN` and `AWS_REGION` — no AWS keys — so the instance role is
picked up automatically and nothing needs editing. Attach a role carrying the policy in
[Minimal IAM policy example](#minimal-iam-policy-example), scoped to the `models/llm/*`
prefix. See [Checking or creating the instance role](#checking-or-creating-the-instance-role).

### Running

Run from the directory holding `mirror.py` — the script sources `./.env`, invokes
`mirror.py` by relative path, and writes the Android artifact into the current directory.

Use `tmux`: the Android path is a plain `curl` with no resume, so an SSH drop mid-transfer
means re-fetching that file from zero.

```bash
tmux new -s mirror
cd /path/to/hf-s3-model-mirror
./mirror_llm_models.sh all
```

> **`--dry-run` is a `mirror.py` flag, not a script flag.** `mirror_llm_models.sh` reads
> only two positional arguments, so a trailing `--dry-run` is *silently ignored* and the
> mirror runs for real. To preview, call the Python directly:
>
> ```bash
> .venv/bin/python mirror.py --repo mlx-community/gemma-4-e2b-it-4bit \
>   --bucket arn:aws:s3:::glycosense-models-v1 \
>   --prefix models/llm/ios/gemma4-e2b/ --zip gemma4-e2b.zip --dry-run
> ```

### Verifying

```bash
aws s3 ls s3://glycosense-models-v1/models/llm/ --recursive --human-readable
```

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

## Checking or creating the instance role

### Is one already attached?

**From the instance** — the quickest check. If a role is attached, this prints an ARN
ending in `:assumed-role/<RoleName>/<instance-id>`:

```bash
aws sts get-caller-identity
```

To get just the role name, query IMDSv2 directly (a 401 here means no role is attached):

```bash
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

**From anywhere**, given the instance ID:

```bash
aws ec2 describe-instances --instance-ids i-0123456789abcdef0 \
  --query 'Reservations[].Instances[].IamInstanceProfile' --output json
```

`null` means nothing is attached.

Having a role is not the same as having the right permissions. Confirm it can actually
write, then clean up after yourself:

```bash
aws s3 cp /etc/hostname s3://glycosense-models-v1/models/llm/_perm-check --region ap-south-1
aws s3 rm s3://glycosense-models-v1/models/llm/_perm-check --region ap-south-1
```

Also confirm the bucket is where you think it is — colocating the instance is the whole
point. An empty `LocationConstraint` means `us-east-1`:

```bash
aws s3api get-bucket-location --bucket glycosense-models-v1
```

### Creating one

Requires `iam:CreateRole`, `iam:PutRolePolicy` and `iam:PassRole` on whatever identity you
run these from.

```bash
# 1. Trust policy — lets EC2 assume the role
cat > /tmp/trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ec2.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
JSON

aws iam create-role --role-name GlycoSenseModelMirror \
  --assume-role-policy-document file:///tmp/trust.json

# 2. Permissions — scoped to the LLM prefix.
#    ListBucket/GetBucketLocation are on the bucket ARN; object actions on the prefix.
cat > /tmp/policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::glycosense-models-v1"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::glycosense-models-v1/models/llm/*"
    }
  ]
}
JSON

aws iam put-role-policy --role-name GlycoSenseModelMirror \
  --policy-name S3ModelMirrorWrite --policy-document file:///tmp/policy.json

# 3. Instance profile — the wrapper EC2 actually attaches.
#    Easy to forget: a role alone cannot be attached to an instance.
aws iam create-instance-profile --instance-profile-name GlycoSenseModelMirror
aws iam add-role-to-instance-profile \
  --instance-profile-name GlycoSenseModelMirror --role-name GlycoSenseModelMirror

# 4. Attach to the running instance (no restart needed)
aws ec2 associate-iam-instance-profile \
  --instance-id i-0123456789abcdef0 \
  --iam-instance-profile Name=GlycoSenseModelMirror
```

Credentials take a few seconds to appear in instance metadata. If the instance already has
a *different* profile attached, `associate` fails — use
`aws ec2 replace-iam-instance-profile-association` instead.

Note that `s3api head-object` (the script's skip-if-exists guard) needs `s3:GetObject`,
which the policy above grants. Delete permission is deliberately omitted: this job never
needs to remove objects, and the legacy `gemma3-1b`/`qwen2.5-0.5b` artifacts must survive
for clients that have not updated yet.

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

- `s3://<bucket>/models/llm/android/gemma4-e4b/gemma-4-E4B-it.litertlm` (3.66 GB)
- `s3://<bucket>/models/llm/android/gemma4-e2b/gemma-4-E2B-it.litertlm` (2.59 GB)
- `s3://<bucket>/models/llm/ios/gemma4-e4b/gemma4-e4b.zip` (~5.15 GB)
- `s3://<bucket>/models/llm/ios/gemma4-e2b/gemma4-e2b.zip` (~3.55 GB)

The legacy `gemma3-1b/` and `qwen2.5-0.5b/` objects are still served to clients that have
not updated yet — do not delete them.

This keeps the mobile-side mapping trivial.

## Serving the models to mobile clients (recommended)

Keep the S3 bucket/prefix private and have your backend mint short-lived pre-signed S3 URLs.

- Example FastAPI service: `presign_api` (see `presign_api/README.md`)
- Mobile app flow: call backend → receive URL → download from S3 (no AWS keys on device)

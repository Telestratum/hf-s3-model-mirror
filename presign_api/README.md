# FastAPI pre-signed URL service

This is a minimal FastAPI app that returns short-lived S3 pre-signed URLs for downloading the mirrored model artifacts.

## Why

- Keep the S3 bucket private.
- Never ship AWS credentials to the mobile app.
- Your backend uses its IAM role to mint pre-signed URLs.

## Models Available

The service provides access to two types of models:

### STT Language Models
- **Path**: `models/indicconformer/{lang}/`
- **Languages**: Hindi (`hi`), Tamil (`ta`), Kannada (`kn`), Telugu (`te`), Malayalam (`ml`)
- **Format**: Single `.nemo` file per language

### LLM Models
- **Android (Gemma 3 1B)**: `models/llm/android/gemma3-1b/gemma3-1b-it-int4.task`
  - Single `.task` file (~1GB)
  - MediaPipe format
  
- **iOS (Qwen 2.5 0.5B)**: `models/llm/ios/qwen2.5-0.5b/`
  - Multiple files (`.safetensors`, config files)
  - MLX format

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r presign_api/requirements.txt

export AWS_REGION=ap-south-1
export AWS_PROFILE=your-profile   # optional (see AWS credentials below)
export API_KEY=change-me          # optional (see env vars below)

uvicorn presign_api.main:app --host 0.0.0.0 --port 8000 --reload
```

## AWS Credentials

The service needs AWS credentials to generate pre-signed URLs. Configure using one of these methods:

### Option 1: AWS Profile (recommended for local development)

```bash
# List available profiles
aws configure list-profiles

# Set profile for the session
export AWS_PROFILE=your-profile-name
```

### Option 2: AWS Access Keys (for environments without profiles)

```bash
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
export AWS_REGION=ap-south-1
```

**Security Note**: Never commit access keys to version control. Use environment variables or `.env` files (which are gitignored).

### Option 3: IAM Role (recommended for production/EC2)

Best practice for production: attach an instance profile/role with permissions:

- `s3:GetObject` on `arn:aws:s3:::glycosense-models-v1/models/indicconformer/*`
- `s3:GetObject` on `arn:aws:s3:::glycosense-models-v1/models/llm/*`

Then you do not need static access keys on the server. boto3 will automatically use the instance role.

### Option 4: .env file (local development)

Create a `.env` file in the `presign_api/` directory:

```bash
# AWS Configuration
AWS_REGION=ap-south-1
AWS_PROFILE=your-profile
# OR
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Authentication (choose one or both)
# JWT Authentication (recommended)
JWT_SECRET=B0a92k7WQvzcZ89z5R5Oh48daDzqZunonvxwL/xnmwI=
JWT_ISSUER=purplehealth-rhmp

# API Key Authentication (legacy)
API_KEY=change-me
```

**Important:** Use the same `JWT_SECRET` as your auth service to validate tokens correctly. The secret should be a Base64-encoded 32-byte string (256 bits for HS256).

## Environment variables

- `S3_BUCKET` (default: `glycosense-models-v1`)
- `S3_PREFIX_BASE` (default: `models/indicconformer`)
- `S3_LLM_PREFIX_BASE` (default: `models/llm`)
- `PRESIGN_TTL_SECONDS` (default: `900`)
- `API_KEY` (default: empty = legacy API key auth disabled)
- `JWT_SECRET` (default: empty = JWT auth disabled)
- `JWT_ISSUER` (default: `purplehealth-rhmp` = expected token issuer)

### Authentication Options

The service supports two authentication methods:

#### Option 1: JWT Authentication (Recommended)

If `JWT_SECRET` is set, clients can authenticate using JWT tokens:

```bash
curl -H "Authorization: Bearer <jwt-token>" http://localhost:8000/v1/models/hi
```

**JWT Token Requirements:**
- Algorithm: HS256 (HMAC with SHA-256)
- Required claims:
  - `exp` - Expiration timestamp (automatically validated)
  - `iss` - Issuer (must match `JWT_ISSUER` setting)
  - Additional claims: `user_id`, `user_uuid`, `role`, `email`, `session_id`
- Header format: `Authorization: Bearer <token>`

**Token validation checks:**
- Signature verification using `JWT_SECRET`
- Expiration time (token must not be expired)
- Issuer claim (must match configured issuer)
- Algorithm (must be HS256)

#### Option 2: API Key Authentication (Legacy)

If `API_KEY` is set, clients can authenticate using a simple API key:

```bash
curl -H "X-API-Key: change-me" http://localhost:8000/v1/models/hi
```

#### Option 3: Both Methods (Backward Compatibility)

Both authentication methods can be enabled simultaneously. The service will:
1. First try JWT authentication if `Authorization` header is present
2. Fall back to API key authentication if `X-API-Key` header is present
3. Return 401 if neither valid authentication is provided

#### No Authentication

If both `JWT_SECRET` and `API_KEY` are empty, authentication is disabled (not recommended for production).

## Endpoints

### STT Language Models

- **`GET /v1/models`** - List all available STT language models
  
  Response:
  ```json
  {
    "bucket": "glycosense-models-v1",
    "prefix_base": "models/indicconformer",
    "models": [
      {
        "lang": "hi",
        "bucket": "glycosense-models-v1",
        "key": "models/indicconformer/hi/indicconformer_stt_hi_hybrid_rnnt_large.nemo"
      }
    ]
  }
  ```

- **`GET /v1/models/{lang}`** - Get pre-signed URL for specific language
  
  Where `lang` is one of: `hi`, `ta`, `kn`, `te`, `ml`
  
  Response:
  ```json
  {
    "bucket": "glycosense-models-v1",
    "key": "models/indicconformer/hi/indicconformer_stt_hi_hybrid_rnnt_large.nemo",
    "url": "https://glycosense-models-v1.s3.amazonaws.com/...",
    "expires_at": "2026-01-30T12:00:00+00:00"
  }
  ```

### LLM Models

- **`GET /v1/llm-models`** - List all available LLM models
  
  Response:
  ```json
  {
    "bucket": "glycosense-models-v1",
    "prefix_base": "models/llm",
    "models": [
      {
        "os": "android",
        "model_name": "gemma3-1b",
        "bucket": "glycosense-models-v1",
        "key": "models/llm/android/gemma3-1b/gemma3-1b-it-int4.task",
        "is_directory": false
      },
      {
        "os": "ios",
        "model_name": "qwen2.5-0.5b",
        "bucket": "glycosense-models-v1",
        "key": "models/llm/ios/qwen2.5-0.5b/",
        "is_directory": true
      }
    ]
  }
  ```

- **`GET /v1/llm-models/{os}/{model_name}`** - Get pre-signed URL for specific LLM model
  
  Where:
  - `os` is one of: `android`, `ios`
  - `model_name` is one of: `gemma3-1b` (Android), `qwen2.5-0.5b` (iOS)
  
  Examples:
  - `GET /v1/llm-models/android/gemma3-1b` - Returns presigned URL for single file
  - `GET /v1/llm-models/ios/qwen2.5-0.5b` - Returns directory info (client must list objects)
  
  Response for single file (Android):
  ```json
  {
    "bucket": "glycosense-models-v1",
    "key": "models/llm/android/gemma3-1b/gemma3-1b-it-int4.task",
    "url": "https://glycosense-models-v1.s3.amazonaws.com/...",
    "expires_at": "2026-01-30T12:00:00+00:00",
    "is_directory": false
  }
  ```
  
  Response for directory (iOS):
  ```json
  {
    "bucket": "glycosense-models-v1",
    "key": "models/llm/ios/qwen2.5-0.5b/",
    "url": "https://glycosense-models-v1.s3.amazonaws.com/models/llm/ios/qwen2.5-0.5b/",
    "expires_at": "2026-01-30T12:00:00+00:00",
    "is_directory": true
  }
  ```

## Example Usage

### Without Authentication

```bash
# List STT models
curl http://localhost:8000/v1/models

# Get presigned URL for Hindi STT model
curl http://localhost:8000/v1/models/hi

# List LLM models
curl http://localhost:8000/v1/llm-models

# Get presigned URL for Android Gemma model
curl http://localhost:8000/v1/llm-models/android/gemma3-1b
```

### With JWT Authentication (Recommended)

```bash
# Set your JWT token
export JWT_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# List STT models
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8000/v1/models

# Get presigned URL for Hindi STT model
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8000/v1/models/hi

# List LLM models
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8000/v1/llm-models

# Get presigned URL for iOS Qwen model
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8000/v1/llm-models/ios/qwen2.5-0.5b
```

### With API Key Authentication (Legacy)

```bash
# List STT models
curl -H "X-API-Key: change-me" http://localhost:8000/v1/models

# Get presigned URL for Hindi STT model
curl -H "X-API-Key: change-me" http://localhost:8000/v1/models/hi

# List LLM models
curl -H "X-API-Key: change-me" http://localhost:8000/v1/llm-models

# Get presigned URL for iOS Qwen model
curl -H "X-API-Key: change-me" http://localhost:8000/v1/llm-models/ios/qwen2.5-0.5b
```

### Error Responses

**401 Unauthorized** - Missing or invalid authentication:
```json
{
  "detail": "Token has expired"
}
```

**401 Unauthorized** - Invalid token format:
```json
{
  "detail": "Invalid authorization header format. Expected: Bearer <token>"
}
```

**401 Unauthorized** - Invalid issuer:
```json
{
  "detail": "Invalid token issuer"
}
```

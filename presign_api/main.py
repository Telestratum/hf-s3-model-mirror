from __future__ import annotations

import jwt
import logging
import logging.handlers
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import boto3
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
import time


Language = Literal["hi", "ta", "kn", "te", "ml"]
ALL_LANGS: tuple[Language, ...] = ("hi", "ta", "kn", "te", "ml")

OS = Literal["android", "ios"]
ModelName = Literal["gemma3-1b", "qwen2.5-0.5b"]

# Map OS to model names
OS_MODELS: dict[OS, tuple[ModelName, ...]] = {
    "android": ("gemma3-1b",),
    "ios": ("qwen2.5-0.5b",),
}


class Settings(BaseSettings):
    # When running from /opt/presign-api with WorkingDirectory=/opt/presign-api
    # the .env file is at presign_api/.env
    model_config = SettingsConfigDict(
        env_file="presign_api/.env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # AWS Configuration
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # S3 location
    s3_bucket: str = "glycosense-models-v1"
    s3_prefix_base: str = "models/indicconformer"
    s3_llm_prefix_base: str = "models/llm"

    # Pre-signed URL TTL
    presign_ttl_seconds: int = 900

    # JWT authentication (required) - must match auth service
    auth_jwt_secret: str  # Same as AUTH_JWT_SECRET in auth service
    jwt_issuer: str = "purplehealth-rhmp"  # Expected issuer claim

    # Logging configuration
    log_level: str = "info"
    log_file_path: str = "./logs/presign-api.log"
    log_max_size_mb: int = 100  # MB
    log_max_backups: int = 5
    log_max_age_days: int = 30
    log_format: str = "json"  # json or text
    environment: str = "production"


settings = Settings()


# Configure structured logging
def setup_logging():
    """Configure structured logging with rotation similar to care service."""
    # Create logs directory if it doesn't exist
    log_dir = Path(settings.log_file_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Set log level
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create custom formatter for JSON-like structured logs
    class StructuredFormatter(logging.Formatter):
        def format(self, record):
            log_data = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname.lower(),
                "service": "presign-api",
                "version": "1.0",
                "environment": settings.environment,
                "message": record.getMessage(),
            }

            # Add extra fields if present
            if hasattr(record, "trace_id"):
                log_data["trace_id"] = record.trace_id
            if hasattr(record, "request_id"):
                log_data["request_id"] = record.request_id
            if hasattr(record, "user_id"):
                log_data["user_id"] = record.user_id
            if hasattr(record, "duration_ms"):
                log_data["duration_ms"] = record.duration_ms
            if hasattr(record, "status_code"):
                log_data["status_code"] = record.status_code
            if hasattr(record, "method"):
                log_data["method"] = record.method
            if hasattr(record, "path"):
                log_data["path"] = record.path
            if hasattr(record, "ip"):
                log_data["ip"] = record.ip

            # Add exception info if present
            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)

            if settings.log_format == "json":
                import json
                return json.dumps(log_data)
            else:
                # Text format for development
                msg = f"{log_data['timestamp']} [{log_data['level'].upper()}] {log_data['message']}"
                if "trace_id" in log_data:
                    msg += f" [trace_id={log_data['trace_id']}]"
                return msg

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.handlers.clear()

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(StructuredFormatter())
    logger.addHandler(console_handler)

    # File handler with rotation (similar to lumberjack)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=settings.log_file_path,
        maxBytes=settings.log_max_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=settings.log_max_backups,
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(StructuredFormatter())
    logger.addHandler(file_handler)

    return logger


# Initialize logging
logger = setup_logging()
logger.info("Presign API service starting up...")

app = FastAPI(
    title="Model Presign API",
    version="1.0",
    description="Pre-signed URL generator for model downloads"
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with distributed tracing support."""
    start_time = time.time()

    # Generate IDs for distributed tracing
    request_id = str(uuid.uuid4())
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

    # Store in request state for use in endpoints
    request.state.request_id = request_id
    request.state.trace_id = trace_id

    # Process request
    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(
            f"Request failed: {str(e)}",
            extra={
                "trace_id": trace_id,
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "ip": request.client.host if request.client else "unknown",
            },
            exc_info=True
        )
        raise

    # Calculate duration
    duration_ms = int((time.time() - start_time) * 1000)

    # Log request
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code}",
        extra={
            "trace_id": trace_id,
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown"),
        }
    )

    # Add trace headers to response
    response.headers["X-Trace-ID"] = trace_id
    response.headers["X-Request-ID"] = request_id

    return response


def _validate_jwt_token(token: str) -> dict:
    """
    Validate JWT token and return claims.

    Args:
        token: JWT token string (without 'Bearer' prefix)

    Returns:
        dict: Token claims including user_id, role, email, etc.

    Raises:
        HTTPException: If token is invalid, expired, or has wrong issuer
    """
    try:
        # Decode and validate token
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={
                "require_exp": True,  # Require expiration claim
                "verify_exp": True,   # Verify token hasn't expired
                "verify_iss": True,   # Verify issuer matches
                "verify_signature": True,  # Verify HMAC signature
            }
        )
        logger.info(f"JWT token validated successfully for user_id: {payload.get('user_id')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.InvalidIssuerError:
        logger.warning(f"Invalid JWT issuer. Expected: {settings.jwt_issuer}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.InvalidSignatureError:
        logger.warning("Invalid JWT signature")
        raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.InvalidAlgorithmError:
        logger.warning("Invalid JWT algorithm")
        raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.DecodeError as e:
        logger.warning(f"JWT decode error: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"JWT validation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid token")


def _require_auth(
    authorization: str | None = Header(default=None, alias="Authorization")
) -> dict:
    """
    Require authentication via JWT token.

    Args:
        authorization: Authorization header (Bearer token)

    Returns:
        dict: JWT claims (user_id, role, email, etc.)

    Raises:
        HTTPException: If authentication fails
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is required"
        )

    # Extract token from "Bearer <token>" format
    parts = authorization.split(" ", 1)  # Split only on first space
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected: Bearer <token>"
        )

    token = parts[1].strip()  # Strip any whitespace

    # Log token length for debugging (don't log actual token)
    logger.debug(f"Validating JWT token (length: {len(token)})")

    claims = _validate_jwt_token(token)
    return claims


def _model_key(lang: Language) -> str:
    # Keep this mapping server-side so clients can't request arbitrary keys.
    # Layout mirrors what mirror_5langs.sh uploads.
    prefix = settings.s3_prefix_base.strip("/")
    return f"{prefix}/{lang}/indicconformer_stt_{lang}_hybrid_rnnt_large.nemo"


def _llm_model_key(os: OS, model: ModelName) -> str:
    # LLM model key mapping for models/llm/{os}/{model}/
    # Android: models/llm/android/gemma3-1b/gemma3-1b-it-int4.task
    # iOS: models/llm/ios/qwen2.5-0.5b/qwen2.5-0.5b.zip
    prefix = settings.s3_llm_prefix_base.strip("/")

    if os == "android" and model == "gemma3-1b":
        return f"{prefix}/{os}/{model}/gemma3-1b-it-int4.task"
    elif os == "ios" and model == "qwen2.5-0.5b":
        return f"{prefix}/{os}/{model}/qwen2.5-0.5b.zip"

    raise ValueError(f"Unknown model configuration: {os}/{model}")


class ModelInfo(BaseModel):
    lang: Language
    bucket: str
    key: str


class ModelsResponse(BaseModel):
    bucket: str
    prefix_base: str
    models: list[ModelInfo]


class LLMModelInfo(BaseModel):
    os: OS
    model_name: ModelName
    bucket: str
    key: str


class LLMModelsResponse(BaseModel):
    bucket: str
    prefix_base: str
    models: list[LLMModelInfo]


class PresignResponse(BaseModel):
    bucket: str
    key: str
    url: str
    expires_at: str


@app.get("/downloader/v1/models/{lang}", response_model=PresignResponse)
def presign_model_download(lang: Language, _claims: dict = Depends(_require_auth)) -> PresignResponse:
    key = _model_key(lang)

    # Create S3 client with explicit credentials from settings
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    try:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=settings.presign_ttl_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URL: {e}")

    expires_at = datetime.now(timezone.utc).timestamp() + settings.presign_ttl_seconds
    return PresignResponse(
        bucket=settings.s3_bucket,
        key=key,
        url=url,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    )


@app.get("/downloader/v1/llm-models/{os}/{model_name}", response_model=PresignResponse)
def presign_llm_model_download(
    os: OS, model_name: ModelName, _claims: dict = Depends(_require_auth)
) -> PresignResponse:
    # Validate OS and model combination
    if model_name not in OS_MODELS.get(os, ()):
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_name}' not available for OS '{os}'. "
            f"Available models: {OS_MODELS.get(os, ())}",
        )

    key = _llm_model_key(os, model_name)

    # Create S3 client with explicit credentials from settings
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    try:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=settings.presign_ttl_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate presigned URL: {e}")

    expires_at = datetime.now(timezone.utc).timestamp() + settings.presign_ttl_seconds
    return PresignResponse(
        bucket=settings.s3_bucket,
        key=key,
        url=url,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    )


@app.get("/downloader/v1/llm-models", response_model=LLMModelsResponse)
def list_llm_models(_claims: dict = Depends(_require_auth)) -> LLMModelsResponse:
    models = []
    for os, model_names in OS_MODELS.items():
        for model_name in model_names:
            models.append(
                LLMModelInfo(
                    os=os,
                    model_name=model_name,
                    bucket=settings.s3_bucket,
                    key=_llm_model_key(os, model_name),
                )
            )
    
    return LLMModelsResponse(
        bucket=settings.s3_bucket,
        prefix_base=settings.s3_llm_prefix_base,
        models=models,
    )


@app.get("/downloader/v1/models", response_model=ModelsResponse)
def list_models(_claims: dict = Depends(_require_auth)) -> ModelsResponse:
    return ModelsResponse(
        bucket=settings.s3_bucket,
        prefix_base=settings.s3_prefix_base,
        models=[
            ModelInfo(lang=lang, bucket=settings.s3_bucket, key=_model_key(lang))
            for lang in ALL_LANGS
        ],
    )


@app.get("/health")
@app.get("/downloader/v1/health")
async def health_check():
    """
    Health check endpoint for load balancers and monitoring.

    Returns service status, version, and basic S3 connectivity check.
    """
    health_status = {
        "status": "healthy",
        "service": "presign-api",
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.environment,
        "checks": {
            "s3_configured": bool(settings.s3_bucket),
            "jwt_configured": bool(settings.auth_jwt_secret),
        }
    }

    # Optional: Quick S3 connectivity check (only if configured)
    if settings.s3_bucket:
        try:
            # Just check if we can create the client with credentials
            # Don't actually call S3 to avoid extra costs and latency
            _ = boto3.client(
                "s3",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            health_status["checks"]["s3_client"] = "ok"
            health_status["checks"]["aws_credentials"] = bool(settings.aws_access_key_id)
        except Exception as e:
            health_status["checks"]["s3_client"] = "error"
            health_status["checks"]["s3_error"] = str(e)
            health_status["status"] = "degraded"
            logger.warning(f"S3 health check failed: {str(e)}")

    # Log health check (only at debug level to avoid spam)
    logger.debug("Health check performed", extra={"status": health_status["status"]})

    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Literal

import boto3
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # S3 location
    s3_bucket: str = "glycosense-models-v1"
    s3_prefix_base: str = "models/indicconformer"
    s3_llm_prefix_base: str = "models/llm"

    # Pre-signed URL TTL
    presign_ttl_seconds: int = 900

    # Optional simple auth. If empty, auth is disabled.
    api_key: str = ""


settings = Settings()
app = FastAPI(title="Model Presign API", version="1.0")


def _require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not settings.api_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _model_key(lang: Language) -> str:
    # Keep this mapping server-side so clients can't request arbitrary keys.
    # Layout mirrors what mirror_5langs.sh uploads.
    prefix = settings.s3_prefix_base.strip("/")
    return f"{prefix}/{lang}/indicconformer_stt_{lang}_hybrid_rnnt_large.nemo"


def _llm_model_key(os: OS, model: ModelName) -> str:
    # LLM model key mapping for models/llm/{os}/{model}/
    # Android: models/llm/android/gemma3-1b/gemma3-1b-it-int4.task
    # iOS: models/llm/ios/qwen2.5-0.5b/ (directory with multiple files)
    prefix = settings.s3_llm_prefix_base.strip("/")
    
    if os == "android" and model == "gemma3-1b":
        return f"{prefix}/{os}/{model}/gemma3-1b-it-int4.task"
    elif os == "ios" and model == "qwen2.5-0.5b":
        # For MLX models, we return the prefix - client needs to list/download all files
        return f"{prefix}/{os}/{model}/"
    
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
    is_directory: bool  # True for iOS/MLX models (multiple files)


class LLMModelsResponse(BaseModel):
    bucket: str
    prefix_base: str
    models: list[LLMModelInfo]


class PresignResponse(BaseModel):
    bucket: str
    key: str
    url: str
    expires_at: str
    is_directory: bool = False  # True for MLX models


@app.get("/v1/models/{lang}", response_model=PresignResponse)
def presign_model_download(lang: Language, _: None = Depends(_require_api_key)) -> PresignResponse:
    key = _model_key(lang)

    # On EC2, prefer attaching an instance profile/role; boto3 will pick it up automatically.
    s3 = boto3.client("s3")

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


@app.get("/v1/llm-models/{os}/{model_name}", response_model=PresignResponse)
def presign_llm_model_download(
    os: OS, model_name: ModelName, _: None = Depends(_require_api_key)
) -> PresignResponse:
    # Validate OS and model combination
    if model_name not in OS_MODELS.get(os, ()):
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_name}' not available for OS '{os}'. "
            f"Available models: {OS_MODELS.get(os, ())}",
        )

    key = _llm_model_key(os, model_name)
    is_directory = os == "ios"  # iOS/MLX models are directories

    s3 = boto3.client("s3")

    if is_directory:
        # For directory (MLX models), return presigned URL for the prefix listing
        # Clients should use this to list all files in the directory
        # Note: S3 doesn't have "directory" presigned URLs, so we'll return the prefix
        # and indicate it's a directory. Clients need to list objects with this prefix.
        return PresignResponse(
            bucket=settings.s3_bucket,
            key=key,
            url=f"https://{settings.s3_bucket}.s3.amazonaws.com/{key}",
            expires_at=datetime.now(timezone.utc).isoformat(),
            is_directory=True,
        )
    else:
        # Single file (Android Gemma)
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
            is_directory=False,
        )


@app.get("/v1/llm-models", response_model=LLMModelsResponse)
def list_llm_models(_: None = Depends(_require_api_key)) -> LLMModelsResponse:
    models = []
    for os, model_names in OS_MODELS.items():
        for model_name in model_names:
            models.append(
                LLMModelInfo(
                    os=os,
                    model_name=model_name,
                    bucket=settings.s3_bucket,
                    key=_llm_model_key(os, model_name),
                    is_directory=os == "ios",
                )
            )
    
    return LLMModelsResponse(
        bucket=settings.s3_bucket,
        prefix_base=settings.s3_llm_prefix_base,
        models=models,
    )


@app.get("/v1/models", response_model=ModelsResponse)
def list_models(_: None = Depends(_require_api_key)) -> ModelsResponse:
    return ModelsResponse(
        bucket=settings.s3_bucket,
        prefix_base=settings.s3_prefix_base,
        models=[
            ModelInfo(lang=lang, bucket=settings.s3_bucket, key=_model_key(lang))
            for lang in ALL_LANGS
        ],
    )

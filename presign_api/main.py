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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # S3 location
    s3_bucket: str = "glycosense-models-v1"
    s3_prefix_base: str = "models/indicconformer"

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


class ModelInfo(BaseModel):
    lang: Language
    bucket: str
    key: str


class ModelsResponse(BaseModel):
    bucket: str
    prefix_base: str
    models: list[ModelInfo]


class PresignResponse(BaseModel):
    bucket: str
    key: str
    url: str
    expires_at: str


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

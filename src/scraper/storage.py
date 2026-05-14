"""Raw-payload storage in S3-compatible object store (MinIO/R2/S3)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from functools import lru_cache

import boto3
from botocore.client import Config

from shared.config import get_settings


@lru_cache(maxsize=1)
def _s3():  # noqa: ANN202
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def raw_s3_key(source_slug: str, source_listing_id: str, fetched_at: datetime, ext: str) -> str:
    month = fetched_at.strftime("%Y-%m")
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    return f"raw/{source_slug}/{month}/{source_listing_id}/{ts}.{ext.lstrip('.')}"


def put_raw(
    source_slug: str,
    source_listing_id: str,
    fetched_at: datetime,
    content_bytes: bytes,
    content_type: str,
) -> tuple[str, str]:
    """Upload raw payload. Returns (s3_key, sha256_hex)."""
    settings = get_settings()
    ext = "json" if "json" in content_type else "html" if "html" in content_type else "bin"
    key = raw_s3_key(source_slug, source_listing_id, fetched_at, ext)
    digest = hashlib.sha256(content_bytes).hexdigest()
    _s3().put_object(
        Bucket=settings.s3_bucket_raw,
        Key=key,
        Body=content_bytes,
        ContentType=content_type,
        Metadata={"sha256": digest},
    )
    return key, digest


def get_raw(s3_key: str) -> bytes:
    settings = get_settings()
    obj = _s3().get_object(Bucket=settings.s3_bucket_raw, Key=s3_key)
    return obj["Body"].read()

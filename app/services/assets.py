"""Image intake (PRD 7): decode-checked PNG/JPEG/WebP, size/pixel limits, original kept,
normalized derivative (EXIF rotation, sRGB-ish RGB) used for preview and PPTX."""
from __future__ import annotations

import hashlib
import io
import warnings

from PIL import Image, ImageOps

from app.config import settings
from app.errors import ApiError

ALLOWED = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def inspect_upload(data: bytes) -> tuple[str, int, int, str]:
    """Return (mime, width, height, sha256) or raise. Width/height are after EXIF rotation."""
    if len(data) > settings.max_image_bytes:
        raise ApiError(413, "FILE_TOO_LARGE", "이미지는 10MB 이하만 업로드할 수 있습니다", "크기를 줄여 다시 업로드")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            fmt = img.format
            img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError(413, "IMAGE_TOO_LARGE", "이미지 픽셀 수가 너무 큽니다", "해상도를 줄여 다시 업로드")
    except Exception:
        raise ApiError(415, "INVALID_IMAGE", "이미지를 읽을 수 없습니다", "PNG/JPEG/WebP 파일을 사용하세요")
    if fmt not in ALLOWED:
        raise ApiError(415, "INVALID_IMAGE", f"지원하지 않는 형식({fmt})", "PNG/JPEG/WebP 파일을 사용하세요")
    img = ImageOps.exif_transpose(img)
    return ALLOWED[fmt], img.width, img.height, hashlib.sha256(data).hexdigest()


def normalized_derivative(data: bytes) -> tuple[bytes, str]:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img.save(out, "PNG", optimize=True)
        return out.getvalue(), "png"
    img = img.convert("RGB")
    img.save(out, "JPEG", quality=92)
    return out.getvalue(), "jpg"


def validate_crop(crop: dict) -> dict:
    try:
        x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        raise ApiError(422, "INVALID_CROP", "crop은 x,y,w,h 숫자여야 합니다", "영역을 다시 선택하세요")
    if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > 1.0001 or y + h > 1.0001:
        raise ApiError(422, "INVALID_CROP", "crop 영역이 이미지 범위를 벗어났습니다", "영역을 다시 선택하세요")
    return {"x": round(x, 6), "y": round(y, 6), "w": round(min(w, 1 - x), 6), "h": round(min(h, 1 - y), 6)}

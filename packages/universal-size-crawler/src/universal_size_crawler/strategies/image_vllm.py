"""이미지 VLLM 전략 — OpenCV bbox 탐지 후 Claude Vision으로 사이즈 추출."""
import base64
import io
import re

import httpx
from PIL import Image

_CHUNK_H = 3000
_OVERLAP = 600

_SIZE_PROMPT = """이 이미지에서 의류 사이즈 차트를 찾아 JSON으로 반환해줘.

반환 형식:
{
  "sizes": {
    "M": {"총장": "59cm", "어깨너비": "44cm"},
    "L": {"총장": "62cm", "어깨너비": "47cm"}
  }
}

사이즈 차트가 없으면 {"sizes": null} 반환."""


def _to_base64(img: Image.Image) -> str:
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


_LOCATE_PROMPT = """이 이미지에서 의류 사이즈 차트(SIZE MEASUREMENTS, 실측 사이즈표 등)가 있는 위치를 찾아줘.

사이즈 차트가 있으면 이미지 전체 높이 대비 시작/끝 위치를 퍼센트(0~100)로 반환:
{"found": true, "y_start_pct": 60, "y_end_pct": 85}

없으면:
{"found": false}

JSON만 반환."""


async def _locate_size_region(img: Image.Image) -> tuple[int, int] | None:
    """Vision 1pass — 썸네일로 사이즈표 y 범위 탐지."""
    # 썸네일로 축소 (높이 1200px 이하)
    w, h = img.size
    if h > 1200:
        scale = 1200 / h
        thumb = img.resize((int(w * scale), 1200), Image.LANCZOS)
    else:
        thumb = img

    from anthropic import AsyncAnthropic
    ac = AsyncAnthropic()
    response = await ac.messages.create(
        model="claude-haiku-4-5-20251001",  # 위치 탐지는 빠른 모델로
        max_tokens=128,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": _to_base64(thumb)},
                },
                {"type": "text", "text": _LOCATE_PROMPT},
            ],
        }],
    )
    text = response.content[0].text
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        import json
        data = json.loads(match.group())
        if data.get("found"):
            y_start = max(0, int(data["y_start_pct"] * h / 100) - 80)
            # 데이터 행이 잘리지 않도록 하단 여유를 충분히 줌
            y_end = min(h, int(data["y_end_pct"] * h / 100) + max(800, int(h * 0.15)))
            return (y_start, y_end)
    except Exception:
        pass
    return None


def _slice_image(img: Image.Image) -> list[Image.Image]:
    w, h = img.size
    chunks = []
    y = 0
    while y < h:
        bottom = min(y + _CHUNK_H, h)
        chunks.append(img.crop((0, y, w, bottom)))
        if bottom == h:
            break
        y += _CHUNK_H - _OVERLAP
    return chunks


def _parse_vision_response(text: str) -> dict[str, dict[str, str]] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        import json
        data = json.loads(match.group())
        sizes = data.get("sizes")
        if sizes and isinstance(sizes, dict):
            return sizes
    except Exception:
        pass
    return None


def _has_api_key() -> bool:
    import os
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def _ask_vision(client, img: Image.Image) -> dict[str, dict[str, str]] | None:
    from anthropic import AsyncAnthropic
    ac = AsyncAnthropic()
    response = await ac.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": _to_base64(img),
                    },
                },
                {"type": "text", "text": _SIZE_PROMPT},
            ],
        }],
    )
    return _parse_vision_response(response.content[0].text)


def _merge_sizes(a: dict, b: dict) -> dict:
    """두 사이즈 dict를 병합 — 같은 사이즈명이면 측정 항목 합산."""
    merged = {k: dict(v) for k, v in a.items()}
    for size_name, measurements in b.items():
        if size_name in merged:
            merged[size_name].update(measurements)
        else:
            merged[size_name] = dict(measurements)
    return merged


async def _process_image(img: Image.Image, client) -> dict[str, dict[str, str]] | None:
    """단일 이미지에서 사이즈 추출 — Vision 2pass (위치 탐지 → 정밀 추출) → 슬라이싱 폴백."""
    w, h = img.size

    # 1pass: 썸네일로 사이즈표 위치 탐지
    region = await _locate_size_region(img)
    if region:
        y_start, y_end = region
        crop = img.crop((0, y_start, w, y_end))
        sizes = await _ask_vision(client, crop)
        if sizes:
            return sizes

    # 슬라이싱 폴백: 각 chunk 결과 병합
    merged: dict = {}
    for chunk in _slice_image(img):
        sizes = await _ask_vision(client, chunk)
        if sizes:
            merged = _merge_sizes(merged, sizes)

    return merged if merged else None


async def extract_from_urls(image_urls: list[str]) -> dict | None:
    """네트워크 인터셉트로 수집한 실제 이미지 URL 목록에서 사이즈 추출."""
    if not image_urls:
        return None
    if not _has_api_key():
        return None

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for url in image_urls[:25]:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
            except Exception:
                continue

            w, h = img.size
            # 세로로 짧거나 정사각형에 가까우면 스킵 (패션 화보, 배너 등)
            if h < 500 or h < w * 1.2:
                continue

            sizes = await _process_image(img, client)
            if sizes:
                return {"source": "image", "product_id": None, "type": "", "sizes": sizes}

    return None

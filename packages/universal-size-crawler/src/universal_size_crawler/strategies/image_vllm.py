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


async def _locate_size_region(img: Image.Image, tracker=None) -> tuple[int, int] | None:
    """Vision 1pass — 썸네일로 사이즈표 y 범위 탐지."""
    w, h = img.size
    if h > 1200:
        scale = 1200 / h
        thumb = img.resize((int(w * scale), 1200), Image.LANCZOS)
    else:
        thumb = img

    from anthropic import AsyncAnthropic
    ac = AsyncAnthropic()
    model = "claude-haiku-4-5-20251001"
    response = await ac.messages.create(
        model=model,
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
    if tracker:
        tracker.record(model, response.usage.input_tokens, response.usage.output_tokens, "vision-locate")
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


async def _ask_vision(
    client, img: Image.Image, tracker=None
) -> dict[str, dict[str, str]] | None:
    from anthropic import AsyncAnthropic
    ac = AsyncAnthropic()
    model = "claude-sonnet-4-6"
    response = await ac.messages.create(
        model=model,
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
    if tracker:
        tracker.record(model, response.usage.input_tokens, response.usage.output_tokens, "vision-extract")
    return _parse_vision_response(response.content[0].text)


def _has_text(img_bytes: bytes) -> bool:
    """OpenCV로 사이즈 차트성 패턴이 없는 이미지를 빠르게 걸러낸다.

    두 신호 중 하나라도 충족하면 True:
    1. 테이블 구조 — 수평선 + 수직선 동시 존재 (경계선이 있는 표)
    2. 소형 텍스트 blob 다수 — 숫자/글자가 빽빽하게 분포 (사이즈 숫자 행)
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(img_bytes, np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return True  # 디코드 실패 시 Vision에 넘김

    h, w = gray.shape
    if h > 800:
        gray = cv2.resize(gray, (int(w * 800 / h), 800))
    h, w = gray.shape

    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 5
    )

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    small = sum(1 for c in contours if 15 < cv2.contourArea(c) < 600)

    # 1. 명확한 테이블 격자 (수평+수직선 모두 뚜렷) + 최소 텍스트
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 5, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 8))
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)
    hr = np.sum(h_lines > 0) / h_lines.size
    vr = np.sum(v_lines > 0) / v_lines.size
    if hr > 0.015 and vr > 0.008 and small > 30:
        return True

    # 2. 촘촘한 소형 blob → 숫자/글자 빽빽 (모델 사진은 95-150, 사이즈 차트는 200+)
    return small > 180


def _is_complete(sizes: dict) -> bool:
    """사이즈 2개 이상 + 각각 유효한 측정값(대시 제외) 3개 이상이면 충분한 결과."""
    if len(sizes) < 2:
        return False
    def valid(m):
        return sum(1 for v in m.values() if v and v not in ("-", "—", ""))
    return all(valid(m) >= 3 for m in sizes.values())


def _merge_sizes(a: dict, b: dict) -> dict:
    """두 사이즈 dict를 병합 — 같은 사이즈명이면 측정 항목 합산."""
    merged = {k: dict(v) for k, v in a.items()}
    for size_name, measurements in b.items():
        if size_name in merged:
            merged[size_name].update(measurements)
        else:
            merged[size_name] = dict(measurements)
    return merged


async def _process_image(img: Image.Image, client, tracker=None) -> dict[str, dict[str, str]] | None:
    """단일 이미지에서 사이즈 추출 — Vision 2pass (위치 탐지 → 정밀 추출) → 슬라이싱 폴백."""
    w, h = img.size

    # 1pass: 썸네일로 사이즈표 위치 탐지
    region = await _locate_size_region(img, tracker=tracker)
    if region:
        y_start, y_end = region
        crop = img.crop((0, y_start, w, y_end))
        sizes = await _ask_vision(client, crop, tracker=tracker)
        if sizes:
            return sizes

    # 슬라이싱 폴백: 각 chunk 결과 병합, 충분한 결과 나오면 조기 종료
    merged: dict = {}
    for chunk in _slice_image(img):
        sizes = await _ask_vision(client, chunk, tracker=tracker)
        if sizes:
            merged = _merge_sizes(merged, sizes)
            if _is_complete(merged):
                break

    return merged if merged else None


async def extract_from_urls(image_urls: list[str], tracker=None) -> dict | None:
    """네트워크 인터셉트로 수집한 실제 이미지 URL 목록에서 사이즈 추출."""
    if not image_urls:
        return None
    if not _has_api_key():
        return None

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for url in image_urls[:15]:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                img_bytes = r.content
                img = Image.open(io.BytesIO(img_bytes))
            except Exception:
                continue

            w, h = img.size
            if h < 500 or h < w * 1.2:
                continue

            if not _has_text(img_bytes):
                continue

            sizes = await _process_image(img, client, tracker=tracker)
            if sizes:
                return {"source": "image", "product_id": None, "type": "", "sizes": sizes}

    return None

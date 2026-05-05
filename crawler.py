"""
무신사 / 유니클로 상품 실측 데이터 크롤러
- 무신사: actual-size API 직접 호출
- 유니클로: size-charts API 직접 호출 (2단계: 상품상세 → 사이즈차트)
"""

import re

import httpx

# ── 공통 ───────────────────────────────────────────────────────────────────

MUSINSA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.musinsa.com",
}

UNIQLO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.uniqlo.com/kr/ko/",
}

SIZE_NAMES = {"XS", "S", "M", "L", "XL", "XXL", "XXXL", "3XL", "2XL", "1XL", "0XL", "FREE", "ONESIZE", "OS"}

UNIQLO_API = "https://www.uniqlo.com/kr/api/commerce/v5/ko"


def detect_url_brand(url: str) -> str | None:
    if "musinsa.com" in url:
        return "musinsa"
    if "uniqlo.com" in url:
        return "uniqlo"
    return None


def fetch_sizes(url: str) -> dict:
    """URL 브랜드를 자동 감지하여 실측 데이터를 반환한다."""
    brand = detect_url_brand(url)
    if brand == "musinsa":
        return fetch_musinsa_sizes(url)
    if brand == "uniqlo":
        return fetch_uniqlo_sizes(url)
    return {"error": "지원하지 않는 쇼핑몰 URL이에요. (무신사, 유니클로 지원)"}


# ── 무신사 ─────────────────────────────────────────────────────────────────

def extract_musinsa_product_id(url: str) -> str | None:
    m = re.search(r"musinsa\.com/(?:products|goods)/(\d+)", url)
    return m.group(1) if m else None


def fetch_musinsa_sizes(url: str) -> dict:
    product_id = extract_musinsa_product_id(url)
    if not product_id:
        return {"error": "무신사 URL에서 상품 ID를 찾을 수 없어요."}

    api_url = f"https://goods-detail.musinsa.com/api2/goods/{product_id}/actual-size"
    try:
        r = httpx.get(api_url, headers=MUSINSA_HEADERS, timeout=8)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"API 요청 실패: {e}"}

    body = r.json()
    if body.get("meta", {}).get("result") != "SUCCESS":
        return {"error": "실측 데이터가 없는 상품이에요."}

    data = body["data"]
    sizes = {}
    for size_entry in data.get("sizes", []):
        name = size_entry["name"]
        sizes[name] = {
            item["name"]: f"{item['value']}cm"
            for item in size_entry.get("items", [])
        }

    return {
        "product_id": product_id,
        "type": data.get("typeName", ""),
        "sizes": sizes,
    }


# ── 유니클로 ───────────────────────────────────────────────────────────────

def extract_uniqlo_product_id(url: str) -> str | None:
    # https://www.uniqlo.com/kr/ko/products/E461215-000/00/
    m = re.search(r"uniqlo\.com/[a-z]{2}/[a-z]{2}/products?/([A-Z0-9\-]+)", url, re.I)
    return m.group(1).upper() if m else None


def fetch_uniqlo_sizes(url: str) -> dict:
    """
    유니클로 상품 페이지 URL → 2단계 API 호출로 사이즈 차트 반환.
    1단계: /products/{id}/price-groups/00/details  → sizeChartUrl 내 상품코드 확인
    2단계: /products/size-charts?productIdsWithColorCode={id}  → 실측 데이터

    반환값 형식 (무신사와 동일):
    {
        "product_id": "E484877-000",
        "type": "유니클로",
        "sizes": {
            "S": {"전체 길이": "66cm", "가슴너비": "56cm", ...},
            "M": {...},
        }
    }
    에러 시: {"error": "메시지"}
    """
    product_id = extract_uniqlo_product_id(url)
    if not product_id:
        return {"error": "유니클로 URL에서 상품 ID를 찾을 수 없어요."}

    api_url = (
        f"{UNIQLO_API}/products/size-charts"
        f"?productIdsWithColorCode={product_id}"
        f"&imageRatio=3x4&includeBodyMeasurements=true&simpleSizeChart=true&httpFailure=true"
    )
    try:
        r = httpx.get(api_url, headers=UNIQLO_HEADERS, timeout=8)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"API 요청 실패: {e}"}

    body = r.json()
    if body.get("status") != "ok":
        return {"error": "사이즈 차트 데이터가 없는 상품이에요."}

    results = body.get("result", [])
    if not results:
        return {"error": "사이즈 차트 데이터가 없는 상품이에요."}

    size_chart = results[0].get("sizeChart", [])
    if not size_chart:
        return {"error": "사이즈 차트가 비어 있어요."}

    sizes = {}
    for entry in size_chart:
        size_name = entry.get("name", "")
        if not size_name:
            continue
        measurements = {}
        for part in entry.get("sizeParts", []):
            part_name = part.get("name", "")
            # cm 단위 값만 사용
            cm_val = next(
                (m["value"] for m in part.get("measurements", []) if m.get("unit") == "cm"),
                None,
            )
            if part_name and cm_val:
                measurements[part_name] = f"{cm_val}cm"
        if measurements:
            sizes[size_name] = measurements

    return {"product_id": product_id, "type": "유니클로", "sizes": sizes}

import re

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.uniqlo.com/kr/ko/",
}

_API_BASE = "https://www.uniqlo.com/kr/api/commerce/v5/ko"


def extract_product_id(url: str) -> str | None:
    m = re.search(r"uniqlo\.com/[a-z]{2}/[a-z]{2}/products?/([A-Z0-9\-]+)", url, re.I)
    return m.group(1).upper() if m else None


def fetch_sizes(url: str) -> dict:
    """
    유니클로 상품 URL → size-charts API 호출 → 사이즈 차트 반환.

    반환값:
    {
        "product_id": "E484877-000",
        "type": "유니클로",
        "sizes": {"S": {"전체 길이": "66cm", ...}, "M": {...}},
    }
    에러 시: {"error": "메시지"}
    """
    product_id = extract_product_id(url)
    if not product_id:
        return {"error": "유니클로 URL에서 상품 ID를 찾을 수 없어요."}

    api_url = (
        f"{_API_BASE}/products/size-charts"
        f"?productIdsWithColorCode={product_id}"
        f"&imageRatio=3x4&includeBodyMeasurements=true&simpleSizeChart=true&httpFailure=true"
    )
    try:
        r = httpx.get(api_url, headers=HEADERS, timeout=8)
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
            cm_val = next(
                (m["value"] for m in part.get("measurements", []) if m.get("unit") == "cm"),
                None,
            )
            if part_name and cm_val:
                measurements[part_name] = f"{cm_val}cm"
        if measurements:
            sizes[size_name] = measurements

    return {"product_id": product_id, "type": "유니클로", "sizes": sizes}

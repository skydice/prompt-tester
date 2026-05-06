import re

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.musinsa.com",
}


def extract_product_id(url: str) -> str | None:
    m = re.search(r"musinsa\.com/(?:products|goods)/(\d+)", url)
    return m.group(1) if m else None


def fetch_sizes(url: str) -> dict:
    """
    무신사 상품 URL → actual-size API 호출 → 사이즈 차트 반환.

    반환값:
    {
        "product_id": "3369756",
        "type": "긴소매티셔츠",
        "sizes": {"M": {"총장": "59cm", ...}, "L": {...}},
    }
    에러 시: {"error": "메시지"}
    """
    product_id = extract_product_id(url)
    if not product_id:
        return {"error": "무신사 URL에서 상품 ID를 찾을 수 없어요."}

    api_url = f"https://goods-detail.musinsa.com/api2/goods/{product_id}/actual-size"
    try:
        r = httpx.get(api_url, headers=HEADERS, timeout=8)
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

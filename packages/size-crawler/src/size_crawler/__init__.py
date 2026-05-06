from .musinsa import fetch_sizes as fetch_musinsa_sizes
from .uniqlo import fetch_sizes as fetch_uniqlo_sizes

__all__ = ["fetch_sizes", "fetch_musinsa_sizes", "fetch_uniqlo_sizes", "detect_url_brand"]


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

"""API 스니핑 전략 — 네트워크 요청 인터셉트로 사이즈 JSON 탐지."""
import json
import re

from playwright.async_api import Page, Request, Response

_SIZE_KEYS = re.compile(
    r"size|measurement|chest|shoulder|waist|length|sleeve|총장|어깨|가슴|사이즈|실측",
    re.I,
)


def _score_json(obj, depth: int = 0) -> int:
    if depth > 5:
        return 0
    if isinstance(obj, dict):
        score = sum(_SIZE_KEYS.search(k) is not None for k in obj)
        return score + sum(_score_json(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return sum(_score_json(item, depth + 1) for item in obj[:10])
    if isinstance(obj, str):
        return 1 if _SIZE_KEYS.search(obj) else 0
    return 0


def _extract_sizes_from_json(obj) -> dict[str, dict[str, str]] | None:
    """JSON에서 sizes 형태 구조 탐색."""
    if not isinstance(obj, dict):
        return None

    # 카페24 actual-size 패턴: sizes[].name + sizes[].items[].name/value
    for key in ("sizes", "sizeList", "size_list", "sizeChart", "size_chart"):
        if key not in obj:
            continue
        size_list = obj[key]
        if not isinstance(size_list, list):
            continue
        result = {}
        for entry in size_list:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("sizeName") or entry.get("label")
            if not name:
                continue
            items = entry.get("items") or entry.get("measurements") or entry.get("sizeParts") or []
            measurements = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                k = item.get("name") or item.get("label") or item.get("partName")
                v = item.get("value") or item.get("cm") or item.get("size")
                if k and v:
                    measurements[k] = f"{v}cm" if "cm" not in str(v) else str(v)
            if measurements:
                result[name] = measurements
        if result:
            return result

    # 재귀 탐색
    for v in obj.values():
        if isinstance(v, (dict, list)):
            found = _extract_sizes_from_json(v) if isinstance(v, dict) else _search_list(v)
            if found:
                return found

    return None


def _search_list(lst) -> dict[str, dict[str, str]] | None:
    for item in lst[:20]:
        if isinstance(item, dict):
            found = _extract_sizes_from_json(item)
            if found:
                return found
    return None


class ApiSniffer:
    def __init__(self):
        self._candidates: list[tuple[int, dict]] = []

    def attach(self, page: Page):
        page.on("response", self._on_response)

    async def _on_response(self, response: Response):
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        try:
            body = await response.json()
        except Exception:
            return
        score = _score_json(body)
        if score >= 3:
            self._candidates.append((score, body))

    def best_result(self) -> dict | None:
        if not self._candidates:
            return None
        _, body = max(self._candidates, key=lambda x: x[0])
        sizes = _extract_sizes_from_json(body)
        if not sizes:
            return None
        return {"source": "api", "product_id": None, "type": "", "sizes": sizes}

"""API 스니핑 전략 — 네트워크 요청 인터셉트로 사이즈 JSON 탐지."""
import json
import os
import re

from playwright.async_api import Page, Response

_SIZE_KEYS = re.compile(
    r"size|measurement|chest|shoulder|waist|length|sleeve|총장|어깨|가슴|사이즈|실측",
    re.I,
)

_CLAUDE_EXTRACT_PROMPT = """아래 JSON에서 의류 사이즈 차트 데이터를 추출해줘.

반환 형식:
{
  "sizes": {
    "M": {"총장": "59cm", "어깨너비": "44cm"},
    "L": {"총장": "62cm", "어깨너비": "47cm"}
  }
}

사이즈 데이터가 없으면 {"sizes": null} 반환. JSON만 반환.

---
"""


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
    """JSON에서 sizes 형태 구조 패턴 매칭."""
    if not isinstance(obj, dict):
        return None

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
            # sizeParts[].measurements[].value 패턴 (유니클로 등)
            size_parts = entry.get("sizeParts") or []
            if size_parts:
                measurements = {}
                for part in size_parts:
                    k = part.get("name") or part.get("partName")
                    raw_measurements = part.get("measurements") or []
                    cm_val = next(
                        (m.get("value") for m in raw_measurements if m.get("unit") == "cm"),
                        None,
                    )
                    if cm_val is None:
                        cm_val = next(
                            (m.get("value") for m in raw_measurements),
                            None,
                        )
                    if k and cm_val is not None:
                        measurements[k] = f"{cm_val}cm" if "cm" not in str(cm_val) else str(cm_val)
                if measurements:
                    result[name] = measurements
                continue
            # items[].name/value 패턴 (무신사 등)
            items = entry.get("items") or entry.get("measurements") or []
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


async def _extract_with_claude(body: dict, tracker=None) -> dict[str, dict[str, str]] | None:
    """패턴 매칭 실패 시 Claude로 JSON 구조 해석."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import AsyncAnthropic
        ac = AsyncAnthropic()
        model = "claude-haiku-4-5-20251001"
        json_str = json.dumps(body, ensure_ascii=False)
        if len(json_str) > 8000:
            json_str = json_str[:8000] + "\n...(truncated)"

        response = await ac.messages.create(
            model=model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": _CLAUDE_EXTRACT_PROMPT + json_str,
            }],
        )
        if tracker:
            tracker.record(model, response.usage.input_tokens, response.usage.output_tokens, "api-extract")
        text = response.content[0].text
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        data = json.loads(match.group())
        sizes = data.get("sizes")
        if sizes and isinstance(sizes, dict):
            return sizes
    except Exception:
        pass
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

    async def best_result(self, tracker=None) -> dict | None:
        if not self._candidates:
            return None
        for _, body in sorted(self._candidates, key=lambda x: x[0], reverse=True):
            sizes = _extract_sizes_from_json(body)
            if sizes:
                return {"source": "api", "product_id": None, "type": "", "sizes": sizes}
            sizes = await _extract_with_claude(body, tracker=tracker)
            if sizes:
                return {"source": "api", "product_id": None, "type": "", "sizes": sizes}
        return None

"""DOM 탐색 전략 — 렌더링된 HTML에서 사이즈 테이블 추출."""
import re

from bs4 import BeautifulSoup

_SIZE_KEYWORDS = re.compile(
    r"총장|어깨|가슴|허리|엉덩이|밑위|허벅지|소매|넥|목|size|shoulder|chest|waist|length|sleeve",
    re.I,
)
_CM_PATTERN = re.compile(r"\d+\.?\d*\s*cm", re.I)
_SIZE_LABELS = re.compile(r"\b(XS|S|M|L|XL|2XL|3XL|FREE)\b", re.I)
_NUMERIC_SIZE = re.compile(r"^[0-9]{2,3}$")
_MEASUREMENT_PART = re.compile(r"총장|어깨|가슴|허리|엉덩이|밑위|허벅지|소매|넥|목|shoulder|chest|waist|length|sleeve", re.I)


_NUMERIC_VALUE = re.compile(r"\d+\.?\d*")


def _score_table(table) -> int:
    """사이즈 테이블일 가능성 점수 (높을수록 좋음)."""
    rows = table.find_all("tr")
    if not rows:
        return 0

    text = table.get_text()

    # 숫자 값이 전혀 없는 테이블은 사이즈표가 아님 (스펙 설명표 등 제외)
    if not _NUMERIC_VALUE.search(text):
        return 0

    score = 0
    score += len(_CM_PATTERN.findall(text)) * 3
    score += len(_SIZE_KEYWORDS.findall(text)) * 2
    score += len(_SIZE_LABELS.findall(text))

    # 헤더 행에 S/M/L/XL이 있으면 강한 보너스 (실제 상품 사이즈표 패턴)
    header_cells = [td.get_text(strip=True) for td in rows[0].find_all(["th", "td"])]
    header_text = " ".join(header_cells)
    size_label_count = len(_SIZE_LABELS.findall(header_text))
    if size_label_count >= 2:
        score += size_label_count * 10

    # 첫 열에 신체 부위명이 있으면 강한 보너스
    first_col = [row.find(["th", "td"]) for row in rows[1:] if row.find(["th", "td"])]
    part_count = sum(1 for td in first_col if td and _MEASUREMENT_PART.search(td.get_text()))
    if part_count >= 2:
        score += part_count * 8

    return score


def _fmt_value(value: str) -> str:
    if not value:
        return value
    if _CM_PATTERN.search(value):
        return value
    # 숫자만 있고 의류 치수 범위면 cm 추가
    num = re.fullmatch(r"(\d+\.?\d*)", value.strip())
    if num and 20 <= float(num.group(1)) <= 250:
        return f"{num.group(1)}cm"
    return value


def _parse_table(table) -> dict[str, dict[str, str]] | None:
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None

    grid = [[td.get_text(strip=True) for td in row.find_all(["th", "td"])] for row in rows]
    if not grid or not grid[0]:
        return None

    headers = grid[0]
    body = grid[1:]

    # 방향 감지: 헤더 행에 S/M/L이 있으면 → 열=사이즈, 행=부위 (전치 필요)
    # 헤더 행에 부위명이 있으면 → 행=사이즈, 열=부위 (그대로)
    header_has_size_labels = sum(1 for h in headers[1:] if _SIZE_LABELS.search(h)) >= 2
    first_col_has_parts = sum(1 for row in body if row and _MEASUREMENT_PART.search(row[0])) >= 2

    if header_has_size_labels:
        # 열=사이즈, 행=부위 → {사이즈명: {부위명: 값}} 으로 전치
        size_names = [h for h in headers[1:] if h]
        sizes: dict[str, dict[str, str]] = {s: {} for s in size_names}
        prev_part_name = ""
        for row in body:
            if not row:
                continue
            # row 길이가 size_names와 같으면 → 라벨 셀 없이 값만 있는 행
            if len(row) == len(size_names):
                part_name = prev_part_name  # 이전 라벨 재사용 (없으면 빈 문자열)
                values = row
            else:
                part_name = row[0]
                values = row[1:]
            if not part_name:
                continue
            prev_part_name = part_name
            for size_name, value in zip(size_names, values):
                v = _fmt_value(value)
                if v:
                    sizes[size_name][part_name] = v
        return {k: v for k, v in sizes.items() if v} or None

    # 기본: 행=사이즈, 열=부위
    sizes = {}
    for row in body:
        if not row:
            continue
        size_name = row[0]
        if not size_name:
            continue
        measurements = {
            headers[i]: _fmt_value(row[i])
            for i in range(1, min(len(headers), len(row)))
            if headers[i] and row[i]
        }
        if measurements:
            sizes[size_name] = measurements

    return sizes if sizes else None


# 텍스트 형식 사이즈 파싱 — "XS_총장61.5 어깨41 ..." 패턴
_SIZE_TEXT_TRIGGER = re.compile(
    r"(XS|XXL|2XL|XL|S|M|L|FREE)_(총장|어깨|가슴|허리|엉덩이|밑위|허벅지|소매|암홀|팔길이|밑단|넥|목)\d",
    re.I,
)
_SIZE_LABEL_SPLIT = re.compile(r"(XS|XXL|2XL|XL|S|M|L|FREE)_", re.I)
_MEASURE_PAIR = re.compile(
    r"(총장|어깨|가슴|허리|엉덩이|밑위|허벅지|소매|암홀|팔길이|밑단|넥|목)(\d+\.?\d*)"
)


def _parse_text_sizes(text: str) -> dict[str, dict[str, str]] | None:
    """'XS_총장61.5 어깨41 가슴49.5 ...' 형식 텍스트 → 구조화된 사이즈 dict."""
    if not _SIZE_TEXT_TRIGGER.search(text):
        return None

    # SIZE_ 기준으로 분리 → [prefix, 'XS', '총장61.5 어깨41 ...', 'S', '총장63 ...', ...]
    parts = _SIZE_LABEL_SPLIT.split(text)
    sizes: dict[str, dict[str, str]] = {}
    i = 1
    while i + 1 < len(parts):
        label = parts[i].upper()
        chunk = parts[i + 1]
        measurements = {
            m.group(1): f"{m.group(2)}cm"
            for m in _MEASURE_PAIR.finditer(chunk)
        }
        if measurements:
            sizes[label] = measurements
        i += 2

    return sizes if sizes else None


def extract(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    # 1순위: HTML 테이블
    tables = soup.find_all("table")
    if tables:
        best = max(tables, key=_score_table)
        if _score_table(best) >= 3:
            sizes = _parse_table(best)
            if sizes:
                return {"source": "dom", "product_id": None, "type": "", "sizes": sizes}

    # 2순위: 텍스트 형식 ("XS_총장61.5 어깨41 ..." 패턴)
    for el in soup.find_all(["ul", "li", "p", "div", "span"]):
        text = el.get_text(separator=" ", strip=True)
        if len(text) > 2000:
            continue
        sizes = _parse_text_sizes(text)
        if sizes:
            return {"source": "dom-text", "product_id": None, "type": "", "sizes": sizes}

    return None

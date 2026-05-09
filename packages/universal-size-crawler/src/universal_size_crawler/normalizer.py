"""사이즈 값 정규화 — 다양한 표기를 통일된 포맷으로."""
import re

_CM_EXTRACT = re.compile(r"(\d+\.?\d*)")
# "01_S", "1. M", "01 XL" → "S", "M", "XL"
_SIZE_NAME_PREFIX = re.compile(r"^\d+[._\-\s]+", )


def normalize_value(v: str) -> str:
    """'590mm', '59', '59.0cm' → '59cm'"""
    v = v.strip()
    if not v:
        return v

    # mm 단위 변환
    mm_match = re.match(r"(\d+\.?\d*)\s*mm", v, re.I)
    if mm_match:
        return f"{float(mm_match.group(1)) / 10:.1f}cm".rstrip("0").rstrip(".")  + "cm"

    # 이미 cm
    if re.search(r"\d.*cm", v, re.I):
        num = _CM_EXTRACT.search(v)
        return f"{num.group(1)}cm" if num else v

    # 숫자만 있고 의류 치수 범위(30~200)면 cm로 간주
    num_match = re.fullmatch(r"(\d+\.?\d*)", v)
    if num_match:
        val = float(num_match.group(1))
        if 20 <= val <= 250:
            return f"{num_match.group(1)}cm"

    return v


def normalize_size_name(name: str) -> str:
    """'01_S', '1. M', '02 XL' → 'S', 'M', 'XL'"""
    return _SIZE_NAME_PREFIX.sub("", name).strip()


def normalize(result: dict) -> dict:
    sizes = result.get("sizes") or {}
    normalized: dict = {}
    for size_name, measurements in sizes.items():
        clean = normalize_size_name(size_name)
        normalized[clean] = {k: normalize_value(v) for k, v in measurements.items()}
    return {**result, "sizes": normalized}

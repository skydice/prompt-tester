# size-crawler

한국 패션 쇼핑몰 사이즈 차트 크롤러 Python 라이브러리.

## 설치

```bash
# 개발 모드 (monorepo workspace에서 자동 처리됨)
uv pip install -e .

# 독립 사용 시
pip install git+https://github.com/...#subdirectory=packages/size-crawler
```

## 사용

```python
from size_crawler import fetch_sizes, fetch_musinsa_sizes, fetch_uniqlo_sizes

# 브랜드 자동 감지
result = fetch_sizes("https://www.uniqlo.com/kr/ko/products/E484877-000")
result = fetch_sizes("https://www.musinsa.com/products/3369756")

# 반환값
{
    "product_id": "E484877-000",
    "type": "유니클로",
    "sizes": {
        "S": {"전체 길이": "66cm", "가슴너비": "56cm", ...},
        "M": {...},
    }
}
```

## 지원 쇼핑몰

| 쇼핑몰 | 방식 | 모듈 |
|--------|------|------|
| 무신사 | actual-size API | `musinsa.py` |
| 유니클로 | size-charts API | `uniqlo.py` |

## 구조

```
packages/size-crawler/
├── pyproject.toml
└── src/size_crawler/
    ├── __init__.py   — fetch_sizes, detect_url_brand export
    ├── musinsa.py    — 무신사 크롤러
    └── uniqlo.py     — 유니클로 크롤러
```

## 새 쇼핑몰 추가

1. `src/size_crawler/{brand}.py` 생성, `fetch_sizes(url) -> dict` 구현
2. `__init__.py`의 `detect_url_brand`, `fetch_sizes`에 분기 추가

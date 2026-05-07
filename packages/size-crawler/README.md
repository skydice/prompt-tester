# size-crawler

한국 패션 쇼핑몰 사이즈 차트 크롤러 Python 라이브러리.

DOM 파싱 없이 각 쇼핑몰의 내부 API를 직접 호출해 실측 사이즈 데이터를 가져온다.

## 지원 쇼핑몰

| 쇼핑몰 | 방식 | 모듈 |
|--------|------|------|
| 무신사 | `actual-size` JSON API | `musinsa.py` |
| 유니클로 | `size-charts` JSON API | `uniqlo.py` |

## 설치

```bash
# monorepo workspace (권장)
uv sync

# 독립 설치
pip install -e packages/size-crawler
```

## 사용

```python
from size_crawler import fetch_sizes

# 브랜드 자동 감지
result = fetch_sizes("https://www.musinsa.com/products/3369756")
result = fetch_sizes("https://www.uniqlo.com/kr/ko/products/E484877-000")

# 반환값
{
    "product_id": "3369756",
    "type": "긴소매티셔츠",
    "sizes": {
        "M": {"총장": "59cm", "어깨너비": "44cm", "가슴단면": "52cm"},
        "L": {"총장": "62cm", "어깨너비": "47cm", "가슴단면": "55cm"},
    }
}

# 에러 시
{"error": "실측 데이터가 없는 상품이에요."}
```

브랜드별 함수를 직접 쓸 수도 있다:

```python
from size_crawler import fetch_musinsa_sizes, fetch_uniqlo_sizes
```

## CLI

```bash
uv run size-crawler https://www.musinsa.com/products/3369756
```

## 새 쇼핑몰 추가

1. `src/size_crawler/{brand}.py` 생성, `fetch_sizes(url: str) -> dict` 구현
2. `__init__.py`의 `detect_url_brand`와 `fetch_sizes`에 분기 추가

반환 형태는 기존 모듈과 동일하게 맞춘다:

```python
{
    "product_id": str,
    "type": str,       # 카테고리명
    "sizes": {
        "사이즈명": {"부위명": "Xcm", ...},
        ...
    }
}
```

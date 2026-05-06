# Fitco

AI 기반 개인 피팅 어드바이저. 착용 이력을 기록하고 LLM이 새 옷의 사이즈를 추천해준다.

## 구조

```
fitco/
├── apps/fitco/            웹 앱 (FastAPI + 단일 HTML 프론트엔드)
└── packages/size-crawler/ 사이즈 차트 크롤러 라이브러리 (무신사, 유니클로)
```

## 시작하기

### 필수 요건

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### 설치

```bash
git clone <repo>
cd fitco
uv sync
```

---

## 웹 앱 실행

```bash
cd apps/fitco
uv run uvicorn server:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속.

### 환경 변수

앱 실행 전 API 키를 UI에서 직접 입력하거나 `.env`로 설정:

```bash
# apps/fitco/.env (선택)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

### 주요 기능

| 탭 | 설명 |
|----|------|
| 피팅 비교 | 상품 URL 또는 이름 입력 → 여러 LLM이 사이즈 추천 동시 비교 |
| 착용 이력 | 구매한 옷의 사이즈·총평 기록 → 이후 추천 정확도 향상 |

- 유니클로·무신사 URL 붙이면 전체 사이즈 차트 자동 로드
- 멀티 유저 프로필 지원 (헤더에서 전환)

---

## 크롤러 CLI

URL 하나로 사이즈 차트를 터미널에서 바로 확인:

```bash
# 테이블 형식 (기본)
uv run size-crawler https://www.uniqlo.com/kr/ko/products/E484877-000

# JSON 형식
uv run size-crawler https://www.musinsa.com/products/3369756 --json
```

### 출력 예시

```
유니클로  E484877-000
────────────────────────────────────────────────────────
항목                         S      M      L     XL    XXL
────────────────────────────────────────────────────────
전체 길이                   66cm   68cm   70cm   73cm   74cm
어깨너비(솔기에서 솔기까지)  49cm  50.5cm  52cm   54cm   56cm
가슴너비                    56cm   59cm   62cm   66cm   70cm
```

### 지원 쇼핑몰

| 쇼핑몰 | URL 예시 |
|--------|---------|
| 유니클로 | `https://www.uniqlo.com/kr/ko/products/E484877-000` |
| 무신사 | `https://www.musinsa.com/products/3369756` |

---

## 개발

### 의존성 추가

```bash
# 웹 앱
uv add --project apps/fitco <package>

# 크롤러 라이브러리
uv add --project packages/size-crawler <package>
```

### 새 쇼핑몰 크롤러 추가

1. `packages/size-crawler/src/size_crawler/{brand}.py` 생성
2. `fetch_sizes(url) -> dict` 구현 (반환 형식은 기존 참고)
3. `__init__.py`의 `detect_url_brand`, `fetch_sizes`에 분기 추가

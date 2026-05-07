# Fitco

AI 기반 개인 피팅 어드바이저. 착용 이력을 기록하고 LLM이 새 옷의 사이즈를 추천해준다.

## 구조

```
fitco/
├── apps/fitco/                       웹 앱 (FastAPI + 단일 HTML 프론트엔드)
├── packages/size-crawler/            사이즈 차트 크롤러 (무신사, 유니클로)
└── packages/universal-size-crawler/  범용 사이즈 차트 크롤러 (카페24 등 모든 쇼핑몰)
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

# universal-size-crawler 이미지 전략 사용 시 (최초 1회)
uv run playwright install chromium
```

### 환경 변수 (루트 `.env`)

```bash
# universal-size-crawler 이미지 분석에 필요
ANTHROPIC_API_KEY=sk-ant-...
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

## 크롤러

### size-crawler — 무신사 / 유니클로 전용

내부 API를 직접 호출하는 경량 크롤러. 빠르고 API 키 불필요.

```bash
uv run size-crawler https://www.uniqlo.com/kr/ko/products/E484877-000
uv run size-crawler https://www.musinsa.com/products/3369756
```

| 쇼핑몰 | 방식 |
|--------|------|
| 유니클로 | `size-charts` JSON API |
| 무신사 | `actual-size` JSON API |

---

### universal-size-crawler — 범용 (카페24 등 모든 쇼핑몰)

어떤 URL이든 DOM 탐색 → API 스니핑 → 이미지 VLLM 순서로 시도한다.

```bash
# URL에 ? 등 특수문자가 있으면 반드시 따옴표
uv run universal-size-crawler 'https://noice1.cafe24.com/shop1/product/detail.html?product_no=1771'
uv run universal-size-crawler 'https://dewaltheritage.cafe24.com/shop1/product/detail.html?product_no=96'
```

출력 예시:

```json
{
  "source": "dom",
  "sizes": {
    "S(95-100)": {"어깨": "49cm", "가슴": "58cm", "소매기장": "60cm", "총기장": "72cm"},
    "M(100-105)": {"어깨": "50.5cm", "가슴": "60.5cm", "소매기장": "61cm", "총기장": "73.5cm"}
  }
}
```

| 전략 | 설명 | 필요 조건 |
|------|------|----------|
| DOM 탐색 | 사이즈 가이드 버튼 클릭 → drawer/modal 파싱 | — |
| API 스니핑 | 네트워크 요청 인터셉트 → JSON 패턴 탐지 | — |
| 이미지 VLLM | 상세 이미지에서 Vision 2-pass로 사이즈표 추출 | `ANTHROPIC_API_KEY` |

자세한 내용 → [`packages/universal-size-crawler/README.md`](packages/universal-size-crawler/README.md)

---

## 개발

### 의존성 추가

```bash
# 웹 앱
uv add --project apps/fitco <package>

# size-crawler
uv add --project packages/size-crawler <package>

# universal-size-crawler
uv add --project packages/universal-size-crawler <package>
```

### 새 쇼핑몰 추가 (size-crawler)

1. `packages/size-crawler/src/size_crawler/{brand}.py` 생성
2. `fetch_sizes(url) -> dict` 구현
3. `__init__.py`의 `detect_url_brand`, `fetch_sizes`에 분기 추가

# Fitco Monorepo

## 구조

```
fitco/
├── apps/fitco/          — AI 피팅 어드바이저 웹 앱 (FastAPI)
└── packages/size-crawler/ — 쇼핑몰 사이즈 차트 크롤러 (Python 라이브러리)
```

## 개발 환경

uv workspace. 루트에서 한 번에 설치:

```bash
uv sync
```

## 주요 명령

```bash
# 웹 앱 실행
cd apps/fitco && uv run uvicorn server:app --reload --port 8000

# 크롤러 빠른 테스트
uv run python -c "from size_crawler import fetch_sizes; print(fetch_sizes('https://www.uniqlo.com/kr/ko/products/E484877-000'))"
```

## 패키지 의존성

`apps/fitco`는 `size-crawler`를 workspace 의존성으로 참조한다.
`apps/fitco/pyproject.toml` → `[tool.uv.sources] size-crawler = { workspace = true }`

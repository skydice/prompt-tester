# universal-size-crawler

어떤 웹 페이지든 URL만 넘기면 사이즈 차트를 추출하는 범용 크롤러.
DOM 탐색 → API 스니핑 → 이미지 VLLM 순서로 폴백하며 최선의 결과를 반환한다.

## 지원 범위

- 카페24 기반 쇼핑몰 (사이즈 가이드 drawer 포함)
- 사이즈 정보를 상세 이미지에 넣은 쇼핑몰 (이미지 VLLM)
- JSON API로 사이즈를 제공하는 쇼핑몰 (API 스니핑)

## 설치

```bash
# monorepo workspace
uv sync
uv run playwright install chromium
```

이미지 VLLM 전략을 사용하려면 `ANTHROPIC_API_KEY`가 필요하다.
프로젝트 루트 `.env`에 아래 형식으로 저장하면 자동으로 로드된다.

```
ANTHROPIC_API_KEY=sk-ant-...
# 또는
claude_api_key=sk-ant-...
```

## 사용

### CLI

```bash
uv run universal-size-crawler 'https://noice1.cafe24.com/shop1/product/detail.html?product_no=1771'
```

URL에 `?` 등 특수문자가 있으면 반드시 따옴표로 감싼다.

### Python

```python
from universal_size_crawler import fetch_sizes

result = fetch_sizes("https://noice1.cafe24.com/shop1/product/detail.html?product_no=1771")
```

### 반환값

```python
{
    "source": "dom",        # 성공한 전략: "dom" | "api" | "image"
    "product_id": None,
    "type": "",
    "sizes": {
        "S(95-100)": {"어깨": "49cm", "가슴": "58cm", "소매기장": "60cm", "총기장": "72cm"},
        "M(100-105)": {"어깨": "50.5cm", "가슴": "60.5cm", "소매기장": "61cm", "총기장": "73.5cm"},
    }
}

# 사이즈 정보 없음
{"error": "사이즈 정보를 찾을 수 없었어요. (DOM/API/이미지 모두 실패)"}
```

## 동작 방식

```
페이지 로드 (Playwright headless)
    │
    ├─ 사이즈 가이드 버튼 탐색 → 클릭 → drawer/modal HTML 우선 파싱
    │
    ├─ 1. DOM 탐색
    │       테이블 점수 기반 탐지 (S/M/L 헤더 보너스, 부위명 보너스)
    │       행/열 방향 자동 감지 후 전치
    │
    ├─ 2. API 스니핑
    │       네트워크 요청 인터셉트 → JSON에서 사이즈 패턴 탐지
    │
    └─ 3. 이미지 VLLM  (ANTHROPIC_API_KEY 필요)
            ec-data-src 등 lazy 이미지 URL 수집
            Vision 2-pass:
              1pass — Haiku 썸네일 → 사이즈표 y 범위 탐지
              2pass — Sonnet 정밀 크롭 → 사이즈 추출
            슬라이싱 폴백 (3000px 청크, 결과 병합)
```

## 패키지 구조

```
packages/universal-size-crawler/
├── pyproject.toml
└── src/universal_size_crawler/
    ├── __init__.py          — fetch_sizes() 동기 진입점
    ├── agent.py             — 전략 오케스트레이션
    ├── cli.py               — CLI (dotenv 자동 로드)
    ├── normalizer.py        — 값 정규화 (mm→cm, 숫자→Xcm)
    └── strategies/
        ├── dom.py           — DOM 테이블 파싱
        ├── api_sniff.py     — 네트워크 인터셉트
        └── image_vllm.py    — Vision 2-pass + 슬라이싱
```

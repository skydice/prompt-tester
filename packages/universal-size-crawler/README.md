# universal-size-crawler

어떤 쇼핑몰 URL이든 넘기면 사이즈 차트를 자동으로 추출하는 범용 크롤러.

카페24처럼 사이즈 정보가 버튼 뒤 drawer에 숨어있거나, 긴 상세 이미지 안에 표로 들어있거나, 내부 JSON API로만 제공되는 경우까지 세 가지 전략을 순서대로 시도해 최선의 결과를 반환한다.

---

## 빠른 시작

### 1. 설치

monorepo 루트에서 한 번만 실행하면 된다.

```bash
uv sync
uv run playwright install chromium
```

### 2. 환경 변수 설정 (이미지 분석 전략 사용 시)

이미지 안에 사이즈표가 있는 쇼핑몰을 지원하려면 Claude API 키가 필요하다.  
프로젝트 루트 `.env` 파일에 저장하면 CLI 실행 시 자동으로 로드된다.

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. 실행

```bash
uv run universal-size-crawler 'URL'
```

URL에 `?`나 `&` 같은 특수문자가 포함되는 경우가 많으므로 **항상 따옴표로 감싼다**.

---

## 사용 예시

### CLI

```bash
# 카페24 — 사이즈 가이드 drawer가 있는 경우
uv run universal-size-crawler 'https://noice1.cafe24.com/shop1/product/detail.html?product_no=1771'

# 카페24 — 상세 이미지 안에 사이즈표가 있는 경우
uv run universal-size-crawler 'https://dewaltheritage.cafe24.com/shop1/product/detail.html?product_no=96'
```

출력 예시:

```json
{
  "source": "dom",
  "product_id": null,
  "type": "",
  "sizes": {
    "S(95-100)": {
      "어깨": "49cm",
      "가슴": "58cm",
      "소매기장": "60cm",
      "총기장": "72cm"
    },
    "M(100-105)": {
      "어깨": "50.5cm",
      "가슴": "60.5cm",
      "소매기장": "61cm",
      "총기장": "73.5cm"
    }
  }
}
```

사이즈 정보가 없는 상품:

```json
{
  "error": "사이즈 정보를 찾을 수 없었어요. (DOM/API/이미지 모두 실패)"
}
```

### Python

```python
from universal_size_crawler import fetch_sizes

result = fetch_sizes("https://noice1.cafe24.com/shop1/product/detail.html?product_no=1771")

if "error" not in result:
    for size_name, measurements in result["sizes"].items():
        print(size_name, measurements)
```

---

## 반환값 스펙

| 필드 | 타입 | 설명 |
|------|------|------|
| `source` | `"dom"` \| `"api"` \| `"image"` | 성공한 전략 |
| `product_id` | `str \| null` | 상품 ID (탐지된 경우) |
| `type` | `str` | 상품 카테고리 (탐지된 경우) |
| `sizes` | `dict` | `{ 사이즈명: { 부위명: "Xcm" } }` |

실패 시 `{ "error": "..." }` 를 반환한다.

---

## 동작 원리

Playwright headless 브라우저로 페이지를 완전히 렌더링한 뒤 세 전략을 순서대로 시도한다. 먼저 성공한 전략의 결과를 즉시 반환한다.

### 사전 단계 — 사이즈 가이드 버튼 클릭

DOM 탐색 전에 페이지에 "사이즈 가이드", "size guide" 등의 텍스트를 가진 버튼이 있으면 자동으로 클릭해 drawer 또는 modal을 열고, 그 HTML을 우선적으로 파싱한다.

### 전략 1 — DOM 탐색

렌더링된 HTML에서 `<table>` 태그를 찾아 사이즈표일 가능성을 점수로 평가한다.

- 헤더 행에 S/M/L/XL이 있으면 강한 보너스
- 첫 열에 어깨·가슴·총장 등 신체 부위명이 있으면 강한 보너스
- 행/열 방향을 자동 감지해 필요하면 전치(transpose)

cm 단위가 없는 숫자(예: `52`)는 의류 치수 범위(20–250)이면 자동으로 `52cm`로 변환한다.

### 전략 2 — API 스니핑

페이지 로드 중 발생하는 모든 네트워크 요청을 인터셉트해 JSON 응답에서 사이즈 패턴을 탐지한다. 무신사·유니클로처럼 내부 REST API를 사용하는 쇼핑몰에서 유효하다.

### 전략 3 — 이미지 VLLM

카페24처럼 사이즈 정보를 긴 세로 상세 이미지 안에 넣는 쇼핑몰을 위한 전략.  
`ANTHROPIC_API_KEY` 설정 시 활성화된다.

**이미지 수집**
- 네트워크 인터셉트로 실제 로드된 이미지 URL 수집
- `ec-data-src` 등 lazy 로딩 속성도 파싱해 병합
- lazy 이미지를 우선적으로 탐색 (상세 이미지일 가능성이 높음)

**Vision 2-pass**

| 단계 | 모델 | 입력 | 목적 |
|------|------|------|------|
| 1pass | claude-haiku (빠름·저렴) | 1200px 축소 썸네일 | 사이즈표가 이미지의 몇 % 위치에 있는지 탐지 |
| 2pass | claude-sonnet (정확) | 해당 영역 크롭 | 사이즈 수치 추출 |

1pass가 위치를 찾지 못하면 이미지를 3000px 청크로 나눠 슬라이싱한다. 각 청크 결과는 병합해 부분 추출을 보완한다.

---

## 패키지 구조

```
packages/universal-size-crawler/
├── pyproject.toml
└── src/universal_size_crawler/
    ├── __init__.py          — fetch_sizes() 동기 진입점
    ├── agent.py             — 전략 오케스트레이션 및 Playwright 제어
    ├── cli.py               — CLI 진입점 (dotenv 자동 로드)
    ├── normalizer.py        — 값 정규화 (mm→cm, 숫자→Xcm)
    └── strategies/
        ├── dom.py           — DOM 테이블 탐지 및 파싱
        ├── api_sniff.py     — 네트워크 인터셉트 및 JSON 패턴 탐지
        └── image_vllm.py    — Vision 2-pass 위치 탐지 및 추출
```

## 의존성

| 패키지 | 용도 |
|--------|------|
| `playwright` | headless 브라우저 렌더링, 네트워크 인터셉트 |
| `beautifulsoup4` + `lxml` | DOM 파싱 |
| `anthropic` | Vision 2-pass (이미지 전략) |
| `pillow` | 이미지 슬라이싱, RGBA→RGB 변환 |
| `opencv-python-headless` | (설치됨, 현재 미사용) |
| `python-dotenv` | `.env` 자동 로드 |

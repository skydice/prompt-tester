# fitco — AI 피팅 어드바이저

FastAPI 웹 앱. 사용자 프로필(신체 치수 + 착용 이력)을 기반으로 LLM이 사이즈를 추천한다.

## 실행

```bash
# monorepo 루트에서
uv sync
cd apps/fitco
uv run uvicorn server:app --reload --port 8000
```

## 구조

```
apps/fitco/
├── server.py          — FastAPI 라우터, LLM 스트리밍, 유저 CRUD
├── prompts/
│   └── personal_fitting.py  — 프롬프트 빌더 (사이즈 차트 → 마크다운 표)
├── profiles/          — 유저 프로필 JSON 저장소 ({user_id}.json)
├── static/index.html  — 프론트엔드 (단일 페이지, Tailwind CDN)
├── eval/              — 프롬프트 평가 스크립트
└── pyproject.toml
```

## 주요 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/users` | 유저 목록 |
| POST | `/users` | 유저 생성 |
| DELETE | `/users/{id}` | 유저 삭제 |
| GET | `/profile?user_id=` | 프로필 조회 |
| POST | `/profile/wearing` | 착용 이력 추가 |
| GET | `/crawl?url=` | 사이즈 차트 크롤링 (size-crawler 위임) |
| POST | `/compare` | LLM 피팅 비교 (SSE 스트리밍) |

## 의존성 추가

```bash
# monorepo 루트에서
uv add --project apps/fitco <package>
```

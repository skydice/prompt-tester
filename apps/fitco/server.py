import asyncio
import json
import time
import uuid
from pathlib import Path

import anthropic
import openai as openai_sdk
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts.personal_fitting import build_prompt
from size_crawler import fetch_sizes

app = FastAPI()

MODELS = {
    "claude-opus-4-7":           {"label": "Opus 4.7",     "provider": "anthropic", "input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":         {"label": "Sonnet 4.6",   "provider": "anthropic", "input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"label": "Haiku 4.5",    "provider": "anthropic", "input": 0.8,   "output": 4.0},
    "gpt-4o":                    {"label": "GPT-4o",        "provider": "openai",    "input": 2.5,   "output": 10.0},
    "gpt-4o-mini":               {"label": "GPT-4o mini",   "provider": "openai",    "input": 0.15,  "output": 0.60},
}

PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)


# ── 프로필 헬퍼 ───────────────────────────────────────────────────────────────

def _profile_path(user_id: str) -> Path:
    return PROFILES_DIR / f"{user_id}.json"


def _load_profile(user_id: str) -> dict:
    p = _profile_path(user_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없어요.")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_profile(user_id: str, profile: dict):
    _profile_path(user_id).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _migrate_legacy():
    """기존 user_profile.json → profiles/default.json 자동 마이그레이션"""
    legacy = PROFILES_DIR / "user_profile.json"
    dest   = _profile_path("default")
    if legacy.exists() and not dest.exists():
        data = json.loads(legacy.read_text(encoding="utf-8"))
        data.setdefault("id",   "default")
        data.setdefault("name", "기본 프로필")
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_migrate_legacy()


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    height_cm: float
    weight_kg: float
    notes: str = ""


class WearingEntry(BaseModel):
    user_id: str
    category: str
    product_name: str
    worn_size: str
    fit: str
    url: str = ""
    size_data: dict = {}


class PreviewRequest(BaseModel):
    user_id: str
    category: str
    product_name: str
    candidate_sizes: str
    measurements: dict = {}
    size_chart: dict = {}
    extra_info: str = ""


class CompareRequest(BaseModel):
    user_id: str = ""
    anthropic_key: str = ""
    openai_key: str = ""
    models: list[str]
    category: str
    product_name: str
    candidate_sizes: str
    measurements: dict = {}
    size_chart: dict = {}
    extra_info: str = ""
    custom_system: str = ""
    custom_user: str = ""


# ── 사용자 관리 ───────────────────────────────────────────────────────────────

@app.get("/users")
def list_users():
    users = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        if p.name == "user_profile.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            users.append({
                "id":           p.stem,
                "name":         data.get("name", p.stem),
                "height_cm":    data.get("body", {}).get("height_cm"),
                "weight_kg":    data.get("body", {}).get("weight_kg"),
                "entry_count":  len(data.get("calibration", [])),
            })
        except Exception:
            pass
    return users


@app.post("/users")
def create_user(req: UserCreate):
    user_id = uuid.uuid4().hex[:8]
    profile = {
        "id":   user_id,
        "name": req.name,
        "body": {
            "height_cm": req.height_cm,
            "weight_kg": req.weight_kg,
            "notes":     req.notes,
        },
        "calibration":             [],
        "inferred_fit_tendencies": {},
    }
    _save_profile(user_id, profile)
    return {"id": user_id, "name": req.name}


@app.delete("/users/{user_id}")
def delete_user(user_id: str):
    p = _profile_path(user_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없어요.")
    p.unlink()
    return {"ok": True}


# ── 프로필 ────────────────────────────────────────────────────────────────────

@app.get("/profile")
def get_profile(user_id: str):
    return _load_profile(user_id)


@app.post("/profile/wearing")
def add_wearing(entry: WearingEntry):
    profile = _load_profile(entry.user_id)
    cal = {
        "category":  entry.category,
        "product":   entry.product_name,
        "worn_size": entry.worn_size,
        "fit":       entry.fit,
        "signals":   {},
    }
    if entry.url:       cal["url"]       = entry.url
    if entry.size_data: cal["size_data"] = entry.size_data
    profile["calibration"].append(cal)
    _save_profile(entry.user_id, profile)
    return {"ok": True, "total": len(profile["calibration"])}


@app.delete("/profile/wearing/{index}")
def delete_wearing(index: int, user_id: str):
    profile = _load_profile(user_id)
    if index < 0 or index >= len(profile["calibration"]):
        raise HTTPException(status_code=400, detail="index out of range")
    profile["calibration"].pop(index)
    _save_profile(user_id, profile)
    return {"ok": True, "total": len(profile["calibration"])}


# ── 크롤러 ────────────────────────────────────────────────────────────────────

@app.get("/crawl")
def crawl(url: str):
    return fetch_sizes(url)


# ── 프롬프트 ──────────────────────────────────────────────────────────────────

@app.post("/preview-prompt")
def preview_prompt(req: PreviewRequest):
    profile = _load_profile(req.user_id)
    system, user = build_prompt(
        category        = req.category,
        product_name    = req.product_name,
        candidate_sizes = req.candidate_sizes,
        measurements    = req.measurements or None,
        size_chart      = req.size_chart or None,
        extra_info      = req.extra_info,
        profile         = profile,
    )
    return {"system": system, "user": user}


@app.get("/models")
def get_models():
    return [
        {"id": k, "label": v["label"], "provider": v["provider"]}
        for k, v in MODELS.items()
    ]


# ── Streaming helpers ──────────────────────────────────────────────────────────

async def _stream_anthropic(client, model, system, user, queue):
    start = time.perf_counter()
    input_tokens = output_tokens = 0
    try:
        async with client.messages.stream(
            model=model, max_tokens=700, system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for chunk in stream.text_stream:
                await queue.put({"model": model, "type": "token", "text": chunk})
            final = await stream.get_final_message()
            input_tokens  = final.usage.input_tokens
            output_tokens = final.usage.output_tokens
    except Exception as e:
        await queue.put({"model": model, "type": "error", "text": str(e)})
        return

    elapsed  = time.perf_counter() - start
    pricing  = MODELS[model]
    cost_usd = input_tokens / 1e6 * pricing["input"] + output_tokens / 1e6 * pricing["output"]
    await queue.put({"model": model, "type": "done", "latency_sec": round(elapsed, 2),
                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                     "cost_usd": round(cost_usd, 6)})


async def _stream_openai(client, model, system, user, queue):
    start = time.perf_counter()
    input_tokens = output_tokens = 0
    try:
        stream = await client.chat.completions.create(
            model=model, max_tokens=700, stream=True,
            stream_options={"include_usage": True},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                await queue.put({"model": model, "type": "token", "text": delta})
            if chunk.usage:
                input_tokens  = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
    except Exception as e:
        await queue.put({"model": model, "type": "error", "text": str(e)})
        return

    elapsed  = time.perf_counter() - start
    pricing  = MODELS[model]
    cost_usd = input_tokens / 1e6 * pricing["input"] + output_tokens / 1e6 * pricing["output"]
    await queue.put({"model": model, "type": "done", "latency_sec": round(elapsed, 2),
                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                     "cost_usd": round(cost_usd, 6)})


@app.post("/compare")
async def compare(req: CompareRequest):
    if req.custom_system or req.custom_user:
        system = req.custom_system
        user   = req.custom_user
    else:
        profile = _load_profile(req.user_id) if req.user_id else {}
        system, user = build_prompt(
            category        = req.category,
            product_name    = req.product_name,
            candidate_sizes = req.candidate_sizes,
            measurements    = req.measurements or None,
            size_chart      = req.size_chart or None,
            extra_info      = req.extra_info,
            profile         = profile or None,
        )

    anthropic_client = anthropic.AsyncAnthropic(api_key=req.anthropic_key) if req.anthropic_key else None
    openai_client    = openai_sdk.AsyncOpenAI(api_key=req.openai_key)      if req.openai_key    else None

    queue    = asyncio.Queue()
    selected = [m for m in req.models if m in MODELS]

    async def generate():
        tasks = []
        for m in selected:
            provider = MODELS[m]["provider"]
            if provider == "anthropic" and anthropic_client:
                tasks.append(asyncio.create_task(_stream_anthropic(anthropic_client, m, system, user, queue)))
            elif provider == "openai" and openai_client:
                tasks.append(asyncio.create_task(_stream_openai(openai_client, m, system, user, queue)))
            else:
                await queue.put({"model": m, "type": "error", "text": f"{provider} API Key가 없어요."})

        done = 0
        while done < len(selected):
            event = await queue.get()
            if event["type"] in ("done", "error"):
                done += 1
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        await asyncio.gather(*tasks, return_exceptions=True)
        yield 'data: {"type":"all_done"}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")

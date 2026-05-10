import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # apps/fitco/.env 자동 로드

import anthropic
import openai as openai_sdk
from google import genai as google_genai
from google.genai import types as genai_types
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts.personal_fitting import build_prompt
from size_crawler import fetch_sizes as fetch_sizes_known
from universal_size_crawler.agent import fetch_sizes as universal_fetch_sizes

app = FastAPI()

MODELS = {
    "claude-opus-4-7":           {"label": "Opus 4.7",          "provider": "anthropic", "input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":         {"label": "Sonnet 4.6",        "provider": "anthropic", "input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"label": "Haiku 4.5",         "provider": "anthropic", "input": 0.8,   "output": 4.0},
    "o3":                        {"label": "o3",                 "provider": "openai",    "input": 10.0,  "output": 40.0},
    "o4-mini":                   {"label": "o4-mini",            "provider": "openai",    "input": 1.1,   "output": 4.4},
    "gemini-2.5-pro":            {"label": "Gemini 2.5 Pro",     "provider": "gemini",    "input": 1.25,  "output": 10.0},
    "gemini-2.5-flash":          {"label": "Gemini 2.5 Flash",   "provider": "gemini",    "input": 0.15,  "output": 0.60},
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
    gemini_key: str = ""
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
async def crawl(url: str, anthropic_key: str = ""):
    known_brands = ("musinsa.com", "uniqlo.com")
    if any(b in url for b in known_brands):
        return fetch_sizes_known(url)
    return await universal_fetch_sizes(url, api_key=anthropic_key)


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
    try:
        cost_usd = input_tokens / 1e6 * pricing["input"] + output_tokens / 1e6 * pricing["output"]
    except Exception:
        cost_usd = 0.0
    await queue.put({"model": model, "type": "done", "latency_sec": round(elapsed, 2),
                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                     "cost_usd": round(cost_usd, 6)})


async def _stream_openai(client, model, system, user, queue):
    start = time.perf_counter()
    input_tokens = output_tokens = 0
    is_o_series = model.startswith("o")
    try:
        stream = await client.chat.completions.create(
            model=model, stream=True,
            stream_options={"include_usage": True},
            **({"max_completion_tokens": 4096} if is_o_series else {"max_tokens": 700}),
            messages=[
                {"role": "developer" if is_o_series else "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                await queue.put({"model": model, "type": "token", "text": delta})
            if chunk.usage:
                input_tokens  = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
    except Exception as e:
        await queue.put({"model": model, "type": "error", "text": str(e)})
        return

    elapsed  = time.perf_counter() - start
    pricing  = MODELS[model]
    try:
        cost_usd = input_tokens / 1e6 * pricing["input"] + output_tokens / 1e6 * pricing["output"]
    except Exception:
        cost_usd = 0.0
    await queue.put({"model": model, "type": "done", "latency_sec": round(elapsed, 2),
                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                     "cost_usd": round(cost_usd, 6)})


async def _stream_gemini(api_key: str, model: str, system: str, user: str, queue):
    start = time.perf_counter()
    input_tokens = output_tokens = 0
    last_error: Exception | None = None

    for attempt in range(3):
        if attempt > 0:
            await asyncio.sleep(5 * attempt)
        input_tokens = output_tokens = 0
        try:
            gclient = google_genai.Client(api_key=api_key)
            config = genai_types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=700,
            )
            stream = await gclient.aio.models.generate_content_stream(
                model=model, contents=user, config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    await queue.put({"model": model, "type": "token", "text": chunk.text})
                if chunk.usage_metadata:
                    if chunk.usage_metadata.prompt_token_count:
                        input_tokens = chunk.usage_metadata.prompt_token_count
                    if chunk.usage_metadata.candidates_token_count:
                        output_tokens = chunk.usage_metadata.candidates_token_count
            last_error = None
            break
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < 2:
                continue
            await queue.put({"model": model, "type": "error", "text": str(e)})
            return

    if last_error is not None:
        await queue.put({"model": model, "type": "error", "text": str(last_error)})
        return

    elapsed  = time.perf_counter() - start
    pricing  = MODELS[model]
    try:
        cost_usd = input_tokens / 1e6 * pricing["input"] + output_tokens / 1e6 * pricing["output"]
    except Exception:
        cost_usd = 0.0
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
            elif provider == "gemini" and req.gemini_key:
                tasks.append(asyncio.create_task(_stream_gemini(req.gemini_key, m, system, user, queue)))
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

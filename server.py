import asyncio
import json
import time

import anthropic
import openai as openai_sdk
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prompts.personal_fitting import build_prompt, PROFILE_PATH
from crawler import fetch_sizes, fetch_uniqlo_sizes

app = FastAPI()

MODELS = {
    "claude-opus-4-7":           {"label": "Opus 4.7",     "provider": "anthropic", "input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":         {"label": "Sonnet 4.6",   "provider": "anthropic", "input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"label": "Haiku 4.5",    "provider": "anthropic", "input": 0.8,   "output": 4.0},
    "gpt-4o":                    {"label": "GPT-4o",        "provider": "openai",    "input": 2.5,   "output": 10.0},
    "gpt-4o-mini":               {"label": "GPT-4o mini",   "provider": "openai",    "input": 0.15,  "output": 0.60},
}


class CompareRequest(BaseModel):
    anthropic_key: str = ""
    openai_key: str = ""
    models: list[str]
    category: str
    product_name: str
    candidate_sizes: str
    measurements: dict = {}
    extra_info: str = ""
    custom_system: str = ""
    custom_user: str = ""


class WearingEntry(BaseModel):
    category: str
    product_name: str
    worn_size: str
    fit: str
    url: str = ""
    size_data: dict = {}


@app.get("/profile")
def get_profile():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


@app.post("/profile/wearing")
def add_wearing(entry: WearingEntry):
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    cal_entry = {
        "category":  entry.category,
        "product":   entry.product_name,
        "worn_size": entry.worn_size,
        "fit":       entry.fit,
        "signals":   {},
    }
    if entry.url:
        cal_entry["url"] = entry.url
    if entry.size_data:
        cal_entry["size_data"] = entry.size_data
    profile["calibration"].append(cal_entry)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "total": len(profile["calibration"])}


@app.delete("/profile/wearing/{index}")
def delete_wearing(index: int):
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if index < 0 or index >= len(profile["calibration"]):
        return {"ok": False, "error": "index out of range"}
    profile["calibration"].pop(index)
    PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "total": len(profile["calibration"])}


@app.get("/crawl")
def crawl(url: str):
    return fetch_sizes(url)


class PreviewRequest(BaseModel):
    category: str
    product_name: str
    candidate_sizes: str
    measurements: dict = {}
    extra_info: str = ""


@app.post("/preview-prompt")
def preview_prompt(req: PreviewRequest):
    system, user = build_prompt(
        category        = req.category,
        product_name    = req.product_name,
        candidate_sizes = req.candidate_sizes,
        measurements    = req.measurements or None,
        extra_info      = req.extra_info,
    )
    return {"system": system, "user": user}


@app.get("/models")
def get_models():
    return [
        {"id": k, "label": v["label"], "provider": v["provider"]}
        for k, v in MODELS.items()
    ]


# ── Streaming helpers ──────────────────────────────────────────────────────

async def _stream_anthropic(client: anthropic.AsyncAnthropic, model: str, system: str, user: str, queue: asyncio.Queue):
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


async def _stream_openai(client: openai_sdk.AsyncOpenAI, model: str, system: str, user: str, queue: asyncio.Queue):
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
        system, user = build_prompt(
            category        = req.category,
            product_name    = req.product_name,
            candidate_sizes = req.candidate_sizes,
            measurements    = req.measurements or None,
            extra_info      = req.extra_info,
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

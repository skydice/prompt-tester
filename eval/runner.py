"""
멀티 모델 테스트 러너
- 여러 모델에 동일 프롬프트 실행
- 속도 / 토큰 / 비용 측정
- 출력 저장 (이후 평가에 사용)
"""

import time
import json
import os
from datetime import datetime
from pathlib import Path
import anthropic

# prompts 디렉토리가 패키지 외부에 있으므로 경로 추가
import sys
sys.path.append(str(Path(__file__).parent.parent))
from prompts.fitting_v1 import (
    build_prompt,
    SAMPLE_MEASUREMENTS,
    SAMPLE_SIZE_GUIDE,
    SAMPLE_REVIEWS,
)

# ── 테스트할 모델 목록 ──────────────────────────────────────────────────────
MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

# 토큰당 가격 (USD, input/output per 1M tokens) — 필요시 업데이트
PRICING = {
    "claude-opus-4-7":          {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":        {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001":{"input": 0.8,   "output": 4.0},
}


def run_single(client: anthropic.Anthropic, model: str, system: str, user: str) -> dict:
    start = time.perf_counter()

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    elapsed = time.perf_counter() - start
    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    text = response.content[0].text

    price = PRICING.get(model, {"input": 0, "output": 0})
    cost_usd = (
        input_tokens  / 1_000_000 * price["input"] +
        output_tokens / 1_000_000 * price["output"]
    )

    return {
        "model": model,
        "output": text,
        "latency_sec": round(elapsed, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
        "chars_per_sec": round(len(text) / elapsed, 1),
    }


def run_all(models: list[str] = MODELS, n_runs: int = 1) -> list[dict]:
    client = anthropic.Anthropic()
    system, user = build_prompt(SAMPLE_MEASUREMENTS, SAMPLE_SIZE_GUIDE, SAMPLE_REVIEWS)

    results = []
    for model in models:
        print(f"\n▶ {model} 실행 중...")
        run_results = []
        for i in range(n_runs):
            r = run_single(client, model, system, user)
            run_results.append(r)
            print(f"  run {i+1}: {r['latency_sec']}s | {r['output_tokens']} out tokens | ${r['cost_usd']}")

        # n_runs > 1이면 평균값 집계
        if n_runs > 1:
            avg = run_results[0].copy()
            avg["latency_sec"]  = round(sum(r["latency_sec"]  for r in run_results) / n_runs, 2)
            avg["output_tokens"]= round(sum(r["output_tokens"] for r in run_results) / n_runs)
            avg["cost_usd"]     = round(sum(r["cost_usd"]      for r in run_results) / n_runs, 6)
            avg["chars_per_sec"]= round(sum(r["chars_per_sec"] for r in run_results) / n_runs, 1)
            avg["runs"] = n_runs
            results.append(avg)
        else:
            run_results[0]["runs"] = 1
            results.append(run_results[0])

    return results


def save_results(results: list[dict], out_dir: str = "eval/outputs") -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{out_dir}/run_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return path


def print_summary(results: list[dict]):
    print("\n" + "="*60)
    print("모델 비교 요약")
    print("="*60)
    header = f"{'모델':<30} {'속도(s)':>8} {'출력토큰':>9} {'비용($)':>10} {'char/s':>8}"
    print(header)
    print("-"*60)
    for r in results:
        print(
            f"{r['model']:<30} {r['latency_sec']:>8} {r['output_tokens']:>9} "
            f"{r['cost_usd']:>10.6f} {r['chars_per_sec']:>8}"
        )


if __name__ == "__main__":
    results = run_all(n_runs=1)
    path = save_results(results)
    print_summary(results)
    print(f"\n결과 저장: {path}")

    # 각 모델 출력 미리보기
    print("\n" + "="*60)
    for r in results:
        print(f"\n{'='*20} {r['model']} {'='*20}")
        print(r["output"][:800], "...[truncated]" if len(r["output"]) > 800 else "")

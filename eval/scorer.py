"""
피팅 설명 품질 자동 평가
- 규칙 기반 체크 (구조 완성도, 키워드 포함 여부)
- LLM-as-judge (Claude가 다른 모델 출력을 평가)
- 결과를 점수 + 근거로 출력
"""

import json
import re
from pathlib import Path
import anthropic

# ── 규칙 기반 평가 ──────────────────────────────────────────────────────────

REQUIRED_SECTIONS = [
    "핵심 피팅 요약",
    "부위별 착용감",
    "사이즈 선택 가이드",
    "잘 맞아요",          # "이런 분께 잘 맞아요" 포함 체크
    "후기 기반 신뢰도",
]

VAGUE_PHRASES = [
    "약간", "조금", "살짝", "좀", "어느 정도",
]

SIZE_RECOMMENDATION_PATTERNS = [
    r"평소\s*\w+\s*(착용|입)",     # "평소 M 착용"
    r"[SMLX]{1,3}\s*(권장|추천|고려)",
    r"한\s*사이즈\s*(업|다운)",
]


def rule_based_score(text: str) -> dict:
    scores = {}

    # 1. 섹션 완성도 (0-5점)
    found = sum(1 for s in REQUIRED_SECTIONS if s in text)
    scores["section_completeness"] = found  # /5

    # 2. 모호한 표현 패널티
    vague_count = sum(text.count(p) for p in VAGUE_PHRASES)
    scores["vague_penalty"] = vague_count   # 낮을수록 좋음

    # 3. 사이즈 추천 명확성 (0-1)
    has_size_rec = any(re.search(p, text) for p in SIZE_RECOMMENDATION_PATTERNS)
    scores["has_size_recommendation"] = int(has_size_rec)

    # 4. 출력 길이 (너무 짧거나 너무 길면 감점)
    char_count = len(text)
    if 300 <= char_count <= 1500:
        scores["length_ok"] = 1
    else:
        scores["length_ok"] = 0
    scores["char_count"] = char_count

    # 5. 체형별 언급 (다양한 체형 커버)
    body_types = ["슬림", "마른", "근육", "보통", "넓은", "힙", "허리"]
    body_count = sum(1 for b in body_types if b in text)
    scores["body_type_coverage"] = min(body_count, 4)  # /4

    total = (
        scores["section_completeness"] * 20      # 최대 100점 환산
        + scores["has_size_recommendation"] * 15
        + scores["length_ok"] * 10
        + scores["body_type_coverage"] * 5       # 최대 20점
        - scores["vague_penalty"] * 3
    )
    scores["rule_total"] = max(0, total)

    return scores


# ── LLM-as-judge 평가 ───────────────────────────────────────────────────────

JUDGE_SYSTEM = """당신은 이커머스 피팅 설명의 품질을 평가하는 전문 심사위원입니다.
주어진 피팅 설명을 다음 5가지 기준으로 각각 1-10점 평가하고, 근거를 한 줄로 설명하세요."""

JUDGE_USER_TEMPLATE = """## 원본 데이터 요약
- 실측: 어깨 44cm, 가슴 102cm (M 사이즈 기준)
- 후기 핵심: 어깨 딱맞음/약간 걸림, 소매 긴 편, 가슴 여유 있음

## 평가할 피팅 설명
{output}

## 평가 기준 (각 1-10점)
1. **구체성**: 수치나 구체적 표현으로 설명했는가? "약간"보다 "1-2cm" 수준
2. **신뢰성**: 후기 내용을 근거로 설명했는가? 데이터에 없는 내용을 지어내지 않았는가?
3. **실용성**: 고객이 읽고 실제로 사이즈 결정에 도움이 되는가?
4. **체형 커버리지**: 다양한 체형/상황을 고려했는가?
5. **가독성**: 구조가 명확하고 읽기 쉬운가?

## 출력 형식 (JSON만 출력)
{{
  "specificity":   {{"score": X, "reason": "..."}},
  "reliability":   {{"score": X, "reason": "..."}},
  "practicality":  {{"score": X, "reason": "..."}},
  "coverage":      {{"score": X, "reason": "..."}},
  "readability":   {{"score": X, "reason": "..."}},
  "total": X,
  "one_line_verdict": "..."
}}"""


def llm_judge_score(client: anthropic.Anthropic, output: str, judge_model: str = "claude-sonnet-4-6") -> dict:
    user = JUDGE_USER_TEMPLATE.format(output=output)
    response = client.messages.create(
        model=judge_model,
        max_tokens=600,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = response.content[0].text.strip()

    # JSON 파싱 (마크다운 코드블록 제거)
    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "JSON 파싱 실패", "raw": raw}


# ── 통합 평가 ───────────────────────────────────────────────────────────────

def evaluate_results(results_path: str, use_llm_judge: bool = True):
    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    client = anthropic.Anthropic() if use_llm_judge else None

    scored = []
    for r in results:
        model = r["model"]
        output = r["output"]
        print(f"\n평가 중: {model}")

        rule = rule_based_score(output)
        entry = {
            "model": model,
            "latency_sec": r["latency_sec"],
            "cost_usd": r["cost_usd"],
            "rule_scores": rule,
        }

        if use_llm_judge and client:
            llm = llm_judge_score(client, output)
            entry["llm_scores"] = llm
            if "total" in llm:
                llm_total = llm["total"]
                entry["combined_score"] = round(rule["rule_total"] * 0.4 + llm_total * 6 * 0.6, 1)
            print(f"  LLM judge: {llm.get('total', 'N/A')}/50 — {llm.get('one_line_verdict', '')}")

        print(f"  Rule score: {rule['rule_total']}/130")
        scored.append(entry)

    return scored


def print_eval_summary(scored: list[dict]):
    print("\n" + "="*70)
    print("평가 결과 요약")
    print("="*70)
    print(f"{'모델':<30} {'규칙점수':>8} {'LLM점수':>9} {'종합':>8} {'속도(s)':>8} {'비용($)':>10}")
    print("-"*70)
    for s in scored:
        llm_total = s.get("llm_scores", {}).get("total", "-")
        combined  = s.get("combined_score", "-")
        print(
            f"{s['model']:<30} {s['rule_scores']['rule_total']:>8} "
            f"{str(llm_total):>9} {str(combined):>8} "
            f"{s['latency_sec']:>8} {s['cost_usd']:>10.6f}"
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        # 가장 최근 결과 파일 자동 선택
        files = sorted(Path("eval/outputs").glob("run_*.json"))
        if not files:
            print("실행할 결과 파일 없음. 먼저 runner.py를 실행하세요.")
            sys.exit(1)
        path = str(files[-1])
    else:
        path = sys.argv[1]

    print(f"평가 파일: {path}")
    scored = evaluate_results(path, use_llm_judge=True)
    print_eval_summary(scored)

    # 평가 결과 저장
    out_path = path.replace("run_", "scored_")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)
    print(f"\n평가 결과 저장: {out_path}")

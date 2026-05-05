"""
사용법:
  python ask.py

대화형으로 옷 정보 입력 → 피팅 코멘트 출력
"""

import anthropic
from prompts.personal_fitting import build_prompt


def ask():
    print("=== 피팅 코멘트 ===")
    print("(실측 없이 URL/제품명만 알아도 됩니다. 실측 있으면 더 정확해요.)\n")

    category     = input("카테고리 (상의/하의/아우터/원피스/스커트 등): ").strip()
    product_name = input("제품명 또는 URL: ").strip()
    sizes        = input("고려 중인 사이즈 (예: S, M 중 고민): ").strip()
    extra        = input("추가 정보 (소재, 핏 설명 등, 없으면 엔터): ").strip()

    print("\n실측 입력 (없으면 그냥 엔터로 넘기세요)")
    measurements = {}
    for key in ["총장", "어깨", "가슴", "허리", "소매", "밑위", "엉덩이"]:
        val = input(f"  {key}: ").strip()
        if val:
            measurements[key] = val

    system, user = build_prompt(
        category=category,
        product_name=product_name,
        candidate_sizes=sizes,
        measurements=measurements if measurements else None,
        extra_info=extra,
    )

    print("\n생각 중...\n" + "─"*40)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    print(response.content[0].text)
    print("─"*40)


if __name__ == "__main__":
    ask()

"""
개인화 피팅 코멘트 생성
- 사용자 프로필(신체 실측 + 착용 이력)을 기반으로
- 새로운 옷에 대한 예상 피팅 코멘트 생성
"""

import json
from pathlib import Path

PROFILE_PATH = Path(__file__).parent.parent / "profiles" / "user_profile.json"


SYSTEM_PROMPT = """당신은 사용자의 체형과 착용 이력을 잘 아는 개인 스타일리스트입니다.
사용자가 새 옷을 살 때, 사이즈와 착용감이 어떨지 솔직하고 구체적으로 조언합니다.

## 조언 원칙
- 사용자의 과거 착용 이력에서 패턴을 찾아 근거로 삼는다
- 실측 데이터가 없으면: 브랜드/카테고리에 대한 일반적인 지식 + 착용 이력 패턴을 조합해서 추론한다
- "예쁠 것 같아요" 같은 공허한 말은 하지 않는다
- 추정일 경우 "이력 기반 추정" 이라고 짧게 표시하면 충분, 길게 disclaimer 달지 않는다
- 결론부터: 어떤 사이즈 / 한 줄 판단"""


def build_profile_summary(profile: dict) -> str:
    body = profile["body"]
    tendencies = profile["inferred_fit_tendencies"]
    calibration = profile["calibration"]

    def size_detail(c: dict) -> str:
        size_data = c.get("size_data", {})
        worn = c.get("worn_size", "")
        if size_data and worn in size_data:
            meas = size_data[worn]
            meas_str = ", ".join(f"{k} {v}" for k, v in meas.items())
            return f" (실측: {meas_str})"
        return ""

    cal_summary = "\n".join(
        f"- {c['category']} {c['worn_size']}: {c['fit']}{size_detail(c)}"
        for c in calibration
    )

    tendency_summary = "\n".join(
        f"- {k}: {v}" for k, v in tendencies.items()
    )

    return f"""키 {body['height_cm']}cm / 몸무게 {body['weight_kg']}kg

## 과거 착용 이력
{cal_summary}

## 체형 패턴 (이력에서 추론)
{tendency_summary}"""


USER_PROMPT_TEMPLATE = """## 내 프로필
{profile_summary}

---

## 살까 고민 중인 옷
카테고리: {category}
브랜드/제품명: {product_name}
고려 중인 사이즈: {candidate_sizes}

제품 실측 (있으면):
{measurements}

추가 정보:
{extra_info}

---

이 옷이 나한테 어떻게 맞을지 코멘트해줘.
형식:
**결론**: (살 것인지 / 어떤 사이즈 / 한 줄 판단)
**가슴/어깨**: (내 체형 특성 감안해서)
**허리·힙·기장**: (해당 있으면)
**주의할 점**: (한 가지만, 없으면 생략)
**근거**: (내 이력 중 어떤 착용 경험을 참고했는지)"""


def build_prompt(
    category: str,
    product_name: str,
    candidate_sizes: str,
    measurements: dict | None = None,
    extra_info: str = "",
) -> tuple[str, str]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile_summary = build_profile_summary(profile)

    if measurements:
        meas_text = "\n".join(f"- {k}: {v}" for k, v in measurements.items())
    else:
        meas_text = "(실측 정보 없음 — 추정으로 답변)"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        profile_summary=profile_summary,
        category=category,
        product_name=product_name,
        candidate_sizes=candidate_sizes,
        measurements=meas_text,
        extra_info=extra_info or "없음",
    )

    return SYSTEM_PROMPT, user_prompt

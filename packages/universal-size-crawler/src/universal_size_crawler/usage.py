"""Claude API 토큰 사용량 및 비용 추적."""
from dataclasses import dataclass, field

# 모델별 가격 (USD / 1M tokens)
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-7":           (15.00, 75.00),
}

_DEFAULT_PRICE = (3.00, 15.00)


def _price(model: str) -> tuple[float, float]:
    for key, price in _PRICING.items():
        if key in model or model in key:
            return price
    return _DEFAULT_PRICE


@dataclass
class UsageTracker:
    calls: list[dict] = field(default_factory=list)

    def record(self, model: str, input_tokens: int, output_tokens: int, note: str = ""):
        in_price, out_price = _price(model)
        cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
        self.calls.append({
            "model": model,
            "note": note,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        })

    def summary(self) -> dict:
        total_in = sum(c["input_tokens"] for c in self.calls)
        total_out = sum(c["output_tokens"] for c in self.calls)
        total_cost = sum(c["cost_usd"] for c in self.calls)
        return {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_cost_usd": round(total_cost, 6),
            "calls": self.calls,
        }

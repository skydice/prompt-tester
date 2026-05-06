import argparse
import json
import sys

from . import fetch_sizes


def _print_table(result: dict) -> None:
    sizes = result["sizes"]
    size_names = list(sizes.keys())

    # 측정 항목 순서 유지
    seen: set = set()
    measurements: list[str] = []
    for data in sizes.values():
        for k in data:
            if k not in seen:
                measurements.append(k)
                seen.add(k)

    meas_w = max(len(m) for m in measurements) + 2
    col_w  = 9

    header = f"{'항목':<{meas_w}}" + "".join(f"{s:>{col_w}}" for s in size_names)
    print(f"\n{result['type']}  {result['product_id']}")
    print("─" * len(header))
    print(header)
    print("─" * len(header))
    for m in measurements:
        row = f"{m:<{meas_w}}" + "".join(
            f"{sizes[s].get(m, '-'):>{col_w}}" for s in size_names
        )
        print(row)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="size-crawler",
        description="쇼핑몰 사이즈 차트 크롤러 (무신사, 유니클로)",
    )
    parser.add_argument("url", help="상품 URL")
    parser.add_argument(
        "--json", dest="as_json", action="store_true", help="JSON 형식으로 출력"
    )
    args = parser.parse_args()

    result = fetch_sizes(args.url)

    if "error" in result:
        print(f"오류: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_table(result)

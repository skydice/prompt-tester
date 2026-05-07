import json
import sys


def main():
    # 현재 디렉터리 및 상위 디렉터리의 .env 자동 로드
    import os
    try:
        from dotenv import load_dotenv, find_dotenv
        load_dotenv(find_dotenv(usecwd=True))
        # claude_api_key → ANTHROPIC_API_KEY 폴백
        if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("claude_api_key"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["claude_api_key"]
    except ImportError:
        pass

    from . import fetch_sizes

    if len(sys.argv) < 2:
        print("사용법: universal-size-crawler <URL>", file=sys.stderr)
        sys.exit(1)
    result = fetch_sizes(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

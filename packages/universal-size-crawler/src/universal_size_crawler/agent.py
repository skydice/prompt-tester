"""전략 오케스트레이션 — DOM → API 스니핑 → 이미지 VLLM 순서로 폴백."""
from playwright.async_api import Page, async_playwright

from .normalizer import normalize
from .strategies import api_sniff, dom, image_vllm
from .usage import UsageTracker

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 사이즈 가이드 버튼 텍스트 키워드 (부분 일치)
_SIZE_BUTTON_KEYWORDS = ["사이즈 가이드", "사이즈가이드", "사이즈 안내", "size guide", "size chart", "사이즈 보기"]

# 클릭 후 visible 상태로 전환되는 drawer/modal 선택자 후보
# 구체적인 것 먼저 — outer wrapper보다 실제 modal 컨테이너가 앞에 와야 함
_DRAWER_SELECTORS = [
    "[class*='typeModal']",
    "[class*='typeDrawer']",
    "[class*='typeSlide']",
    "[class*='sizeLayer']",
    "[class*='size-layer']",
    "[class*='size_layer']",
    "[class*='size-guide']",
    "[class*='size_guide']",
    "[id*='sizeguide']",
    "[id*='sizeGuide']",
    "[class*='sizeguide']",
    "[class*='ec-base-layer']",
]


async def _dismiss_overlays(page: Page):
    """쿠키 동의, 뉴스레터 팝업 등 클릭을 막는 오버레이 닫기."""
    dismiss_selectors = [
        "#onetrust-accept-btn-handler",
        "[id*='cookie'] button",
        "[class*='cookie'] button",
        "[id*='consent'] button",
        "[aria-label='닫기']",
        "[aria-label='Close']",
        "button[class*='close']",
        "button[class*='dismiss']",
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible():
                await btn.click(timeout=1_500)
                await page.wait_for_timeout(300)
        except Exception:
            continue


async def _try_open_size_drawer(page: Page) -> bool:
    """사이즈 가이드 버튼을 찾아 클릭하고 drawer가 열리면 True 반환.

    핵심: 텍스트가 짧은 leaf 요소만 클릭 후보로 삼아 큰 wrapper div 오클릭 방지.
    """
    await _dismiss_overlays(page)

    for kw in _SIZE_BUTTON_KEYWORDS:
        candidates = page.locator("a, button, span").filter(has_text=kw)
        count = await candidates.count()
        for i in range(count):
            el = candidates.nth(i)
            try:
                text = (await el.inner_text()).strip()
                # 텍스트가 짧아야 실제 버튼 (wrapper div 제외)
                if len(text) > 40:
                    continue
                await el.click(timeout=3_000)
                await _wait_for_drawer(page)
                return True
            except Exception:
                continue
    return False


async def _wait_for_drawer(page: Page):
    """drawer/modal visible 대기 — 최대 2초."""
    for sel in _DRAWER_SELECTORS:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=2_000)
            return
        except Exception:
            continue
    await page.wait_for_timeout(1_000)


async def _extract_drawer_html(page: Page) -> str | None:
    """열린 drawer/modal의 HTML만 추출 — 'cm' 텍스트를 포함한 가장 작은 visible 요소."""
    for sel in _DRAWER_SELECTORS:
        try:
            locator = page.locator(sel).filter(has_text="cm")
            count = await locator.count()
            if count == 0:
                continue
            # visible한 것만
            for i in range(count):
                el = locator.nth(i)
                if await el.is_visible():
                    return await el.inner_html()
        except Exception:
            continue
    return None


def _collect_lazy_image_urls(html: str, base_url: str) -> list[str]:
    """ec-data-src, data-src 등 lazy 속성 이미지 URL 수집."""
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    urls = []
    lazy_attrs = ["ec-data-src", "data-src", "data-lazy-src", "data-original"]
    for img in soup.find_all("img"):
        for attr in lazy_attrs:
            src = img.get(attr)
            if src and not src.startswith("data:"):
                urls.append(urljoin(base_url, src))
                break
    return urls


async def fetch_sizes(url: str, api_key: str = "") -> dict:
    tracker = UsageTracker()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(extra_http_headers=_HEADERS)
        page = await context.new_page()

        sniffer = api_sniff.ApiSniffer()
        sniffer.attach(page)

        # 네트워크에서 실제 로드된 이미지 URL 수집 (HTML src 오조합 방지)
        intercepted_images: list[tuple[int, str]] = []

        async def _on_image_response(response):
            ct = response.headers.get("content-type", "")
            if "image" in ct and response.status == 200:
                try:
                    body = await response.body()
                    if len(body) > 50_000:
                        intercepted_images.append((len(body), response.url))
                except Exception:
                    pass

        page.on("response", _on_image_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as e:
            await browser.close()
            return {"error": f"페이지 로드 실패: {e}"}
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3_000)  # XHR/iframe 완료 대기

        # 사이즈 가이드 버튼 클릭 시도
        opened = await _try_open_size_drawer(page)

        # drawer가 열렸으면 drawer HTML 우선, 아니면 전체 페이지 HTML
        drawer_html = None
        if opened:
            drawer_html = await _extract_drawer_html(page)

        html = await page.content()

        # iframe 내 사이즈 차트 수집 (snapfit 등 서드파티 사이즈 서비스)
        frame_htmls: list[str] = []
        for frame in page.frames[1:]:  # 메인 프레임 제외
            frame_url = frame.url
            if not frame_url or frame_url in ("about:blank", "") or "google" in frame_url or "facebook" in frame_url or "criteo" in frame_url or "kakao" in frame_url:
                continue
            try:
                fhtml = await frame.content()
                frame_htmls.append(fhtml)
            except Exception:
                continue

        await browser.close()

    def _with_usage(result: dict) -> dict:
        if tracker.calls:
            result["usage"] = tracker.summary()
        return result

    # 1. DOM 탐색 — drawer HTML 우선, 메인 페이지, iframe 순
    if drawer_html:
        result = dom.extract(drawer_html)
        if result:
            return _with_usage(normalize(result))

    result = dom.extract(html)
    if result:
        return _with_usage(normalize(result))

    for fhtml in frame_htmls:
        result = dom.extract(fhtml)
        if result:
            return _with_usage(normalize(result))

    # 2. API 스니핑
    result = await sniffer.best_result(tracker=tracker)
    if result:
        return _with_usage(normalize(result))

    # 3. 이미지 VLLM — lazy 속성 URL 우선, 네트워크 인터셉트 폴백
    lazy_urls = _collect_lazy_image_urls(html, url)
    intercepted_urls = [u for _, u in sorted(intercepted_images, reverse=True)]
    image_urls = lazy_urls + intercepted_urls
    seen: set[str] = set()
    image_urls = [u for u in image_urls if not (u in seen or seen.add(u))]
    result = await image_vllm.extract_from_urls(image_urls, tracker=tracker, api_key=api_key)
    if result:
        return _with_usage(normalize(result))

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"error": "사이즈 정보를 찾을 수 없었어요. (DOM/API 실패, 이미지 분석은 ANTHROPIC_API_KEY 설정 필요)"}
    return {"error": "사이즈 정보를 찾을 수 없었어요. (DOM/API/이미지 모두 실패)"}

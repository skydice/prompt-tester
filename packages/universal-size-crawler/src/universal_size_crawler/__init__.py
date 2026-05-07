import asyncio

from .agent import fetch_sizes as _async_fetch_sizes

__all__ = ["fetch_sizes"]


def fetch_sizes(url: str) -> dict:
    """URL을 받아 사이즈 차트를 반환한다 (동기 진입점)."""
    return asyncio.run(_async_fetch_sizes(url))

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def bounded_gather(
    items: Sequence[T], worker: Callable[[T], Awaitable[R]], *, concurrency: int
) -> list[R]:
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    sem = asyncio.Semaphore(concurrency)

    async def _one(item: T) -> R:
        async with sem:
            return await worker(item)

    return list(await asyncio.gather(*[_one(item) for item in items]))

import asyncio
import sys
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


def _run_in_proactor_loop(coro_fn: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
    """Run an async coroutine inside a fresh ProactorEventLoop in a dedicated thread."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn(*args, **kwargs))
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            loop.close()
            asyncio.set_event_loop(None)


async def run_with_subprocess_loop(coro_fn: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
    """
    Execute an async function requiring subprocess support (e.g. Playwright).
    
    On Windows, if the currently running event loop is a SelectorEventLoop
    (common when running Uvicorn with --reload or workers > 1), asyncio subprocess
    calls raise NotImplementedError. This function detects that condition and
    delegates execution to a worker thread running a ProactorEventLoop.
    
    In all other cases (ProactorEventLoop or Unix platforms), it executes directly
    in the current loop.
    """
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    needs_proactor_thread = (
        sys.platform == "win32"
        and current_loop is not None
        and isinstance(current_loop, getattr(asyncio, "SelectorEventLoop", ()))
    )

    if needs_proactor_thread:
        return await asyncio.to_thread(_run_in_proactor_loop, coro_fn, *args, **kwargs)

    return await coro_fn(*args, **kwargs)

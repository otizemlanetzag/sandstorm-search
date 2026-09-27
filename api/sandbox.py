"""Process isolation for Sandstorm's untrusted site scanner.

The scanner never executes site JavaScript. It is nevertheless isolated in a
separate Python process with strict time/memory/CPU limits. On POSIX systems
the worker also receives OS resource limits. Network access remains limited
by the scanner's SSRF protections.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import traceback
from typing import Any, Callable


TIMEOUT_SECONDS = 15
MEMORY_LIMIT_MB = 256
CPU_LIMIT_SECONDS = 12


def _apply_limits() -> None:
    if os.name != "posix":
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
        memory = MEMORY_LIMIT_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError):
        # The application still has process + timeout isolation on platforms
        # where POSIX resource limits are unavailable.
        pass


def _worker(fn: Callable[..., Any], args: tuple[Any, ...], result_queue) -> None:
    _apply_limits()
    try:
        result_queue.put(("ok", fn(*args)))
    except BaseException as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def run_in_sandbox(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a scanner in a short-lived isolated worker process."""
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_worker, args=(fn, args, result_queue), daemon=True)
    process.start()
    process.join(TIMEOUT_SECONDS)

    if process.is_alive():
        process.kill()
        process.join(2)
        raise TimeoutError("Sandbox terminated the scan because it exceeded the time limit.")

    try:
        status, value = result_queue.get_nowait()
    except queue.Empty:
        raise RuntimeError("Sandbox worker stopped without returning a result.")

    if status == "error":
        raise RuntimeError(value)
    return value

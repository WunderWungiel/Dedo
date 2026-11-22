"""A tiny in-process TTL cache for reference data."""

import functools
import threading
import time

# Every cache created by ttl_cache, so clear() can reset all of them.
_CACHES = []


def ttl_cache(seconds):
    """Cache the decorated function's results for `seconds`.

    The key is the call arguments. The wrapper exposes cache_clear().
    """

    def decorator(function):
        entries = {}
        lock = threading.Lock()

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                cached = entries.get(key)
                if cached is not None and cached[0] > now:
                    return cached[1]

            value = function(*args, **kwargs)

            with lock:
                entries[key] = (time.monotonic() + seconds, value)
            return value

        def cache_clear():
            with lock:
                entries.clear()

        wrapper.cache_clear = cache_clear
        _CACHES.append((entries, lock))
        return wrapper

    return decorator


def clear():
    """Clear every cache created by this module."""
    for entries, lock in list(_CACHES):
        with lock:
            entries.clear()

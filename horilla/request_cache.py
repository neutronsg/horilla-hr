"""
Per-request memoisation for read-only context processors and lookups.

Django renders a page's context processors, and horilla_views.render_template()
renders them again for every templated cell (memoised once per request), so each
settings lookup ran at least twice per request. Results here are stored on the
request object and therefore never outlive or cross requests.
"""

from functools import wraps

_MISSING = object()


def per_request(func):
    """Cache ``func(request)`` on the request for the rest of that request."""
    key = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if request is None or args or kwargs:
            return func(request, *args, **kwargs)
        store = request.__dict__.setdefault("_neutron_request_cache", {})
        value = store.get(key, _MISSING)
        if value is _MISSING:
            value = store[key] = func(request)
        return value

    return wrapper


def request_value(request, key, compute):
    """Return ``compute()`` once per request under ``key`` (no caching without a request)."""
    if request is None:
        return compute()
    store = request.__dict__.setdefault("_neutron_request_cache", {})
    value = store.get(key, _MISSING)
    if value is _MISSING:
        value = store[key] = compute()
    return value

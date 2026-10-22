"""Rate-limit concurrency, expiry, capacity and forwarded-header regressions."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.auth_limits import AttemptLimiter, RateLimited
import app.auth_routes as auth


def test_five_attempts_then_wait_until_window_expires():
    now = [0]
    limiter = AttemptLimiter(clock=lambda: now[0])
    for _ in range(5):
        limiter.check('client')
    with pytest.raises(RateLimited) as result:
        limiter.check('client')
    assert result.value.retry_after == 900
    now[0] = 900
    limiter.check('client')


def test_concurrent_attempts_cannot_exceed_limit():
    limiter = AttemptLimiter()
    def attempt(_):
        try:
            limiter.check('client')
            return True
        except RateLimited:
            return False
    with ThreadPoolExecutor(max_workers=12) as executor:
        assert sum(executor.map(attempt, range(40))) == 5


def test_key_capacity_is_bounded_and_expired_keys_are_reclaimed():
    now = [0]
    limiter = AttemptLimiter(max_keys=2, clock=lambda: now[0])
    limiter.check('a')
    limiter.check('b')
    with pytest.raises(RateLimited):
        limiter.check('c')
    assert len(limiter.attempts) == 2
    now[0] = 900
    limiter.check('c')
    assert list(limiter.attempts) == ['c']


def test_forwarded_headers_do_not_change_app_rate_limit_key(monkeypatch):
    limiter = AttemptLimiter()
    monkeypatch.setattr(auth, '_limiter', limiter)
    for index in range(5):
        request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'), headers={'x-forwarded-for': str(index)})
        auth._rate_limit(request, 'login')
    request.headers['x-forwarded-for'] = 'new-address'
    with pytest.raises(HTTPException) as result:
        auth._rate_limit(request, 'login')
    assert result.value.status_code == 429
    assert int(result.value.headers['Retry-After']) > 0
    assert len(limiter.attempts) == 1

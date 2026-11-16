import pytest

from tryon_backend import access


def test_tokens_verify_only_with_the_right_secret():
    token = access.sign("device-1", "s" * 32)
    assert access.verify(token, "s" * 32) == "device-1"
    assert access.verify(token, "t" * 32) is None
    assert access.verify(token[:-1] + ("0" if token[-1] != "0" else "1"), "s" * 32) is None
    assert access.verify("device-2." + token.split(".")[1], "s" * 32) is None
    assert access.verify("", "s" * 32) is None and access.verify("nodot", "s" * 32) is None


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


def test_hourly_limit_and_recovery():
    clock = Clock()
    limiter = access.Limiter(per_device_hourly=2, per_device_daily=10, global_daily=100, clock=clock)
    for _ in range(2):
        limiter.check("a"); limiter.record("a")
    with pytest.raises(access.LimitExceeded) as hit:
        limiter.check("a")
    assert hit.value.scope == "device_hourly" and 0 < hit.value.retry_after <= 3601
    limiter.check("b")                       # other devices are unaffected
    clock.now = 3601
    limiter.check("a")                       # an hour later it works again


def test_daily_and_global_limits():
    clock = Clock()
    limiter = access.Limiter(per_device_hourly=100, per_device_daily=3, global_daily=5, clock=clock)
    for _ in range(3):
        limiter.check("a"); limiter.record("a")
    with pytest.raises(access.LimitExceeded) as hit:
        limiter.check("a")
    assert hit.value.scope == "device_daily"
    for _ in range(2):
        limiter.check("b"); limiter.record("b")
    with pytest.raises(access.LimitExceeded) as hit:
        limiter.check("c")
    assert hit.value.scope == "service_daily"
    clock.now = 86401
    limiter.check("a"); limiter.check("c")


def test_cost_counts_several_generations_at_once():
    limiter = access.Limiter(per_device_hourly=3, per_device_daily=10, global_daily=100, clock=Clock())
    limiter.check("a", cost=3)
    with pytest.raises(access.LimitExceeded):
        limiter.check("a", cost=4)
    limiter.record("a", cost=3)
    assert limiter.remaining("a") == {"hour": 0, "day": 7}

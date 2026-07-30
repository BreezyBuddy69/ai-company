"""The supervisor decides how much work to start. Its failure modes are
asymmetric: starting too little wastes ten minutes, starting too much burns the
day's free-model rate limit in one tick. These cover the "too much" side."""

from app import tasks


class _Inspector:
    def __init__(self, active=None, reserved=None, raises=False):
        self._active, self._reserved, self._raises = active, reserved, raises

    def active(self):
        if self._raises:
            raise ConnectionError("broker down")
        return self._active

    def reserved(self):
        return self._reserved


def _patch_inspect(monkeypatch, inspector):
    monkeypatch.setattr(
        tasks.celery_app.control, "inspect", lambda *a, **k: inspector, raising=False
    )


def test_counts_active_and_reserved_across_workers(monkeypatch):
    _patch_inspect(
        monkeypatch,
        _Inspector(active={"w1": [1, 2], "w2": [3]}, reserved={"w1": [4]}),
    )
    assert tasks._inflight() == 4


def test_unreachable_workers_count_as_busy(monkeypatch):
    """inspect() returns None when no worker answers — a restart, a broker
    blip. Reading that as "nothing running" would dispatch a full batch into a
    system whose real state is unknown, every tick, forever."""
    _patch_inspect(monkeypatch, _Inspector(active=None, reserved=None))
    assert tasks._inflight() == tasks.CEILING_INFLIGHT


def test_inspect_raising_counts_as_busy(monkeypatch):
    _patch_inspect(monkeypatch, _Inspector(raises=True))
    assert tasks._inflight() == tasks.CEILING_INFLIGHT


def test_supervisor_does_nothing_while_the_pool_is_full(monkeypatch):
    monkeypatch.setattr(tasks, "_inflight", lambda: tasks.TARGET_INFLIGHT)
    # No DB session is opened at all on this path — if the guard regressed,
    # this test would fail on the database connection rather than the assert.
    assert tasks.run_supervisor()["skipped"] == "busy"


def test_budget_never_exceeds_target(monkeypatch):
    """Regression guard on the arithmetic: budget is what gets handed to the
    stage dispatchers, so an off-by-one here is an over-dispatch every tick."""
    for inflight in range(0, tasks.TARGET_INFLIGHT):
        budget = min(tasks.TARGET_INFLIGHT - inflight, tasks.CEILING_INFLIGHT - inflight)
        assert 0 < budget <= tasks.TARGET_INFLIGHT


def test_ceiling_is_above_target():
    # Inverted, the budget goes negative and the supervisor silently stops
    # dispatching anything at all.
    assert tasks.CEILING_INFLIGHT > tasks.TARGET_INFLIGHT
    assert tasks.MAX_PER_STAGE > 0

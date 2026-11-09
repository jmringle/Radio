"""Learns a fox's on/off pattern (many transmit in bursts, e.g. 30 s every 2 min) and predicts the
next transmission, so a quiet gap mid-sweep isn't mistaken for pointing the wrong way."""
from collections import deque
from statistics import median

ON_DB, OFF_DB = 6.0, 3.0  # two thresholds, so a signal hovering near one doesn't flicker on and off
DEBOUNCE = 3  # readings (0.3 s) a change must last
KEEP = 6  # transmissions remembered: the pattern follows recent behavior
NEED_STARTS = 3  # three starts give two intervals to compare


def _consistent(intervals: list[float]) -> float | None:
    """The period if the intervals agree within 20% (or 2 s, for short ones), else None."""
    if len(intervals) < NEED_STARTS - 1:
        return None
    period = median(intervals)
    return period if all(abs(i - period) <= max(0.2 * period, 2.0) for i in intervals) else None


def _s(seconds: float) -> str:
    return f"{round(seconds)} s"


class Schedule:
    def __init__(self):
        self.clear()

    def clear(self) -> None:
        """A new frequency is a different fox."""
        self.on = False
        self.since: float | None = None  # when the current on or off state began
        self.pending = 0  # readings in a row that disagree with the current state
        self.pending_since: float | None = None
        self.starts: deque[float] = deque(maxlen=KEEP)
        self.durations: deque[float] = deque(maxlen=KEEP)

    def update(self, t: float, over_noise_db: float, overload: bool) -> None:
        """One reading at time t (seconds, any steady clock)."""
        if self.since is None:
            self.since = t
        looks_on = overload or over_noise_db >= (OFF_DB if self.on else ON_DB)
        if looks_on == self.on:
            self.pending = 0
            return
        if self.pending == 0:
            self.pending_since = t
        self.pending += 1
        if self.pending < DEBOUNCE:
            return
        changed_at = self.pending_since  # it really changed when it first looked different
        if looks_on:
            self.starts.append(changed_at)
        elif self.starts and self.starts[-1] >= self.since:  # an off after a start we saw
            self.durations.append(changed_at - self.starts[-1])
        self.on, self.since, self.pending = looks_on, changed_at, 0

    @property
    def heard(self) -> bool:
        return bool(self.starts)

    @property
    def fox_off(self) -> bool:
        """Between transmissions of a fox we've heard (not just a weak fox never heard)."""
        return self.heard and not self.on

    @property
    def period(self) -> float | None:
        s = list(self.starts)
        return _consistent([b - a for a, b in zip(s, s[1:])])

    def status(self, t: float) -> dict:
        """What the page shows: on/off, the learned pattern and the wait for the next transmission."""
        period = self.period
        duration = median(self.durations) if self.durations else None
        status = {"on": self.on, "period_s": period, "duration_s": duration, "next_in_s": None}
        if not self.heard:
            status["text"] = "No transmission heard yet." if not self.on else ""
            return status
        elapsed = t - self.since
        usually = f" (usually about {_s(duration)})" if duration else ""
        if self.on:
            status["text"] = f"Fox on the air for {_s(elapsed)}{usually}."
            return status
        if period is None:
            irregular = len(self.starts) >= NEED_STARTS
            status["text"] = (f"Fox off for {_s(elapsed)}; "
                              + ("its timing is irregular (or there's more than one fox)." if irregular
                                 else f"learning its pattern (needs {NEED_STARTS} transmissions)."))
            return status
        next_in = self.starts[-1] + period - t
        status["next_in_s"] = next_in
        pattern = f"every {_s(period)}" + (f", on for {_s(duration)}" if duration else "")
        if next_in >= 0:
            status["text"] = f"Next transmission in about {_s(next_in)} ({pattern})."
        elif -next_in <= max(0.5 * period, 5.0):
            status["text"] = f"Next transmission due now ({pattern})."
        else:
            status["text"] = f"Overdue by {_s(-next_in)}: the pattern may have changed ({pattern})."
        return status

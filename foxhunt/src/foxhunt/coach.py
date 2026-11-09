"""Attenuator coaching: what to change when the signal is too strong or too weak to hunt with.
Works from the last second of readings so one odd reading doesn't flip the advice. The thresholds
are starting values, to be tuned on real hunts."""
from collections import deque
from statistics import median

WINDOW = 10  # readings, about 1 s
WEAK_DB = 6.0  # below this, extra attenuation may be hiding the fox
STRONG_DB = 45.0  # an 8-bit dongle has about 48 dB of range (6 dB per bit), so leave room to rise
CLOSE_ATT_DB = 60.0  # still strong with this much attenuation: the fox is very near

OVERLOAD = "Overloaded: add 10 dB of attenuation"
STRONG = "Strong: add 20 dB of attenuation so the meter has room to show it getting stronger."
CLOSE = ("Very close: the fox is probably within sight. Hold the antenna against your chest and turn "
         "slowly; the signal drops most when your body is between the antenna and the fox.")
WEAK = "Weak: remove 10 dB of attenuation so you don't lose the fox in the noise."


class Coach:
    def __init__(self):
        self.recent: deque[dict] = deque(maxlen=WINDOW)

    def clear(self) -> None:
        """Settings changed: the old readings no longer describe what the dongle sees."""
        self.recent.clear()

    def update(self, reading: dict, fox_off: bool = False) -> str | None:
        """Advice for the page, or None. fox_off: the fox is known to be between transmissions,
        so the noise now says nothing about the attenuator."""
        if fox_off:
            self.recent.clear()
            return None
        self.recent.append(reading)
        if any(r["overload"] for r in self.recent):
            lower = " (or lower the gain)" if reading["gain_db"] > 0 else ""
            return f"{OVERLOAD}{lower}, then enter the new attenuator value under Settings."
        if len(self.recent) < WINDOW:
            return None  # not enough to judge yet
        level = median(r["over_noise_db"] for r in self.recent)
        attenuator = reading["attenuator_db"]
        if level > STRONG_DB:
            return CLOSE if attenuator >= CLOSE_ATT_DB else STRONG
        if level < WEAK_DB and attenuator > 0:
            return WEAK
        return None

"""Stream quality: the levels a room offers, the viewer's choice (Auto or a fixed level), and Auto's rules."""
import math
from dataclasses import dataclass

AUTO = 'auto'


@dataclass(frozen=True)
class Tier:
    id: str           # Huya: the bitrate in kbps ('20000'); Douyin: the quality name ('origin')
    label: str        # what the menus show, e.g. '20 Mbps' or 'Original · 1080p · 5.2 Mbps'
    mbps: float
    url: str
    video: bool = True    # False for audio only: offered in the menu, but never picked by Auto or a bitrate cap


def parse(text):
    """The -q/--quality value -> AUTO, a bitrate cap in Mbps (8 or 2.5; 2000 is read as kbps, the old form),
    or a Douyin quality name (origin, hd, sd, ld, md)."""
    t = (text or AUTO).strip().lower()
    if t == AUTO:
        return AUTO
    try:
        v = float(t)
    except ValueError:
        return t
    return v / 1000 if v >= 100 else v


def pick(tiers, choice, cap=math.inf):
    """The level to play from tiers (best first): Auto takes the best within Auto's cap; a cap in Mbps takes the
    best at or below it; a quality name takes that level. Falls back to the best, or for a cap to the lowest."""
    if not tiers:
        raise LookupError('the room offers no stream')
    video = [t for t in tiers if t.video] or tiers
    if choice == AUTO or choice is None:
        choice = cap
    if isinstance(choice, str):
        return next((t for t in tiers if t.id == choice), video[0])
    return next((t for t in video if t.mbps <= choice + 0.01), video[-1])


class Auto:
    """Auto's rules. Step down one level when the buffer runs dry for more than STALL_LONG seconds, or twice within
    STALL_WINDOW seconds. After CALM seconds without a stall, try one level up; if that stalls within PROBE seconds,
    go back down and don't try again for HOLD seconds. Stalls in the first GRACE seconds of a level don't count:
    the buffer is still filling."""
    STALL_LONG, STALL_WINDOW, CALM, PROBE, HOLD, GRACE = 4, 60, 300, 120, 1200, 15

    def __init__(self):
        self.cap = math.inf                          # the highest bitrate Auto allows right now
        self.last_stall = self.probe_until = self.hold_until = -math.inf
        self.last_change = 0.0

    def changed(self, now: float, probing: bool = False) -> None:
        """A new level (or room) started playing."""
        self.last_change = now
        self.probe_until = now + self.PROBE if probing else -math.inf

    def stall_started(self, now: float) -> bool:
        """The buffer ran dry. True: step down now (a second stall soon after the first, or a failed try upwards)."""
        if now - self.last_change < self.GRACE:
            return False
        failed_probe = now < self.probe_until
        if failed_probe:
            self.hold_until = now + self.HOLD
        repeat = now - self.last_stall < self.STALL_WINDOW
        self.last_stall = now
        return failed_probe or repeat

    def stall_long(self, now: float) -> bool:
        """Still dry STALL_LONG seconds after a stall started. True: step down."""
        return now - self.last_change >= self.GRACE

    def may_step_up(self, now: float) -> bool:
        return (now - self.last_stall >= self.CALM and now - self.last_change >= self.CALM
                and now >= self.hold_until)

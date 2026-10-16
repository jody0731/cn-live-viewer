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


class Flow:
    """How the playing stream moves, from samples about a second apart: how fast it arrives (the newest buffered
    timestamp against the clock) and how it plays (the playback position against the clock, and mpv's A/V offset).
    After a room or level switch mpv sometimes plays the picture fast, out of step with the sound, until the buffer
    is empty. That stall is not the connection: the stream kept arriving in real time. Auto steps down only when it
    didn't, and a picture racing ahead is put back in step with the sound."""
    WINDOW, MIN_SPAN, IN_TIME = 20, 5, 0.95          # arrival: judged over up to 20 s (at least 5), in time >= 95 %
    RACE_SPAN, RACE_RATE, OUT_OF_STEP = 2, 1.15, 0.3  # racing: 15 % faster than the clock for 2 s, or A/V 0.3 s apart
    JUMP = 5                                         # the position moving 5 s more than the clock: a jump, not racing

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """A new stream: forget everything."""
        self.arrived = []                            # (now, newest buffered timestamp)
        self.restart_play()

    def restart_play(self) -> None:
        """Playback jumped (a seek) or stopped (a pause, an empty buffer): playback speed starts over."""
        self.played = []                             # (now, playback position, A/V offset) while playing steadily

    def sample(self, now: float, newest, pos, playing: bool, avsync=None) -> None:
        if newest is not None:
            if self.arrived:
                t, n = self.arrived[-1]
                if not -1 <= newest - n <= now - t + 10:     # the timestamps jumped: a new or restarted stream
                    self.arrived = []
            self.arrived.append((now, newest))
        if playing and pos is not None:
            if self.played:
                t, p, _ = self.played[-1]
                if not -1 <= pos - p <= now - t + self.JUMP:  # a timestamp jump in the stream
                    self.restart_play()
            self.played.append((now, pos, avsync))
        else:
            self.restart_play()
        self.arrived = [a for a in self.arrived if now - a[0] <= self.WINDOW]
        self.played = [p for p in self.played if now - p[0] <= self.RACE_SPAN + 0.5]

    def arriving_in_time(self):
        """True: the stream arrives at least as fast as it plays, so an empty buffer isn't the connection.
        False: it arrives too slowly. None: not enough samples yet."""
        if len(self.arrived) < 2 or self.arrived[-1][0] - self.arrived[0][0] < self.MIN_SPAN:
            return None
        (t0, n0), (t1, n1) = self.arrived[0], self.arrived[-1]
        return (n1 - n0) / (t1 - t0) >= self.IN_TIME

    def out_of_step(self) -> bool:
        """The picture races ahead of the clock, or picture and sound drifted apart, for the last few seconds."""
        if len(self.played) < 2 or self.played[-1][0] - self.played[0][0] < self.RACE_SPAN:
            return False
        (t0, p0, _), (t1, p1, _) = self.played[0], self.played[-1]
        racing = (p1 - p0) / (t1 - t0) > self.RACE_RATE
        apart = all(a is not None and abs(a) > self.OUT_OF_STEP for _, _, a in self.played)
        return racing or apart

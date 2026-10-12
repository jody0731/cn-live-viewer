"""The computer's graphics chips, power source and load, for the Video Decoder.

Graphics chips are listed by mpv itself, so the names are the ones mpv accepts back: Windows (Direct3D 11)
`--d3d11-adapter=help`, Linux and other Unix (Vulkan) `--vulkan-device=help`. macOS picks its graphics chip by itself.
A computer with a weak built-in chip and a strong separate one (most gaming laptops) runs Efficient on the built-in
chip and High quality on the separate one; with one chip, the two modes are only different settings."""
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass

WINDOWS = os.name == 'nt'
VENDORS = {0x10de: 'nvidia', 0x1002: 'amd', 0x8086: 'intel'}
SOFTWARE = re.compile(r'llvmpipe|lavapipe|softpipe|swiftshader|basic render|microsoft basic', re.I)


@dataclass(frozen=True)
class Gpu:
    name: str          # as mpv lists it (and accepts it back)
    vendor: str        # nvidia, amd, intel or other
    discrete: bool     # a separate graphics card (or a laptop's separate chip), not one built into the processor


def is_discrete(name: str, vendor: str) -> bool:
    """Built-in chips: Intel's (except the Arc A and B cards) and AMD's Radeon Graphics / Vega / 680M-style ones."""
    if vendor == 'nvidia':
        return True
    if vendor == 'intel':
        return bool(re.search(r'\bArc\b.*\b[AB]\d{3}', name))
    if vendor == 'amd':
        return bool(re.search(r'\bRX\b|\bPro W|\bFirePro\b|Radeon VII|Instinct', name))
    return False


def gpu(name: str, vendor_id: int):
    """A Gpu, or None for a software renderer (it draws on the CPU)."""
    name = name.strip()
    if not name or SOFTWARE.search(name):
        return None
    vendor = VENDORS.get(vendor_id, 'other')
    return Gpu(name, vendor, is_discrete(name, vendor))


def parse_vulkan(text: str) -> list:
    """mpv --vulkan-device=help:  'NVIDIA GeForce RTX 3080' (GPU 0, PCI ID 10de:2216, UUID ...)"""
    out = []
    for name, vendor in re.findall(r"^\s*'(.+)' \(GPU \d+, PCI ID ([0-9a-fA-F]+):", text, re.M):
        g = gpu(name, int(vendor, 16))
        if g and g not in out:
            out.append(g)
    return out


def parse_dxgi(text: str) -> list:
    """mpv --d3d11-adapter=help:  Adapter 0: vendor: 4318, description: NVIDIA GeForce RTX 4060 Laptop GPU"""
    out = []
    for vendor, name in re.findall(r'Adapter \d+: vendor: (\d+), description: (.+)', text):
        g = gpu(name, int(vendor))
        if g and g not in out:
            out.append(g)
    return out


def detect(mpv: str) -> list:
    """The graphics chips mpv can draw on (a second or so). Empty on macOS, or when mpv can't tell."""
    if sys.platform == 'darwin':
        return []
    option, parse = ('--d3d11-adapter=help', parse_dxgi) if WINDOWS else ('--vulkan-device=help', parse_vulkan)
    try:
        r = subprocess.run([mpv, '--no-config', option], capture_output=True, text=True, errors='replace', timeout=10,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse(r.stdout + r.stderr)


def to_dicts(gpus) -> list:
    return [{'name': g.name, 'vendor': g.vendor, 'discrete': g.discrete} for g in gpus]


def from_dicts(items) -> list:
    try:
        return [Gpu(str(i['name']), str(i['vendor']), bool(i['discrete'])) for i in items]
    except (KeyError, TypeError):
        return []


def split(gpus):
    """-> (the chip for Efficient, the chip for High quality), or (None, None) to leave the choice to the system:
    only a computer with both a built-in and a separate chip gets one of each."""
    built_in = [g for g in gpus if not g.discrete]
    separate = [g for g in gpus if g.discrete]
    if not built_in or not separate:
        return None, None
    rank = {'nvidia': 0, 'amd': 1, 'intel': 2}
    return built_in[0], min(separate, key=lambda g: rank.get(g.vendor, 3))


def gpu_options(g) -> dict:
    """The mpv options that draw (and hardware-decode) on this chip; {} for the system's choice."""
    if g is None:
        return {}
    if WINDOWS:
        return {'d3d11-adapter': g.name}
    return {'gpu-api': 'vulkan', 'vulkan-device': g.name}


# ---------------------------------------------------------------- power and load

def on_battery():
    """True on battery, False on mains power, None when there's no battery (or it can't tell)."""
    try:
        if WINDOWS:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('ac', ctypes.c_ubyte), ('flag', ctypes.c_ubyte), ('percent', ctypes.c_ubyte),
                            ('saver', ctypes.c_ubyte), ('life', ctypes.c_ulong), ('full', ctypes.c_ulong)]
            s = Status()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) or s.flag & 128 or s.ac == 255:
                return None                          # 128: no system battery (a desktop)
            return s.ac == 0
        if sys.platform == 'darwin':
            out = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True, timeout=5).stdout
            if 'InternalBattery' not in out:
                return None
            return "'Battery Power'" in out
        return linux_on_battery('/sys/class/power_supply')
    except Exception:                                # noqa: BLE001 - a guess either way; Auto then ignores power
        return None


def linux_on_battery(root: str):
    """From /sys/class/power_supply: the computer's own batteries (not a mouse's or a headset's, scope Device)."""
    def read(dev, key):
        try:
            with open(os.path.join(root, dev, key), encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''
    try:
        devices = os.listdir(root)
    except OSError:
        return None
    batteries = [d for d in devices if read(d, 'type') == 'Battery' and read(d, 'scope') != 'Device']
    if not batteries:
        return None
    if any(read(d, 'type') in ('Mains', 'USB') and read(d, 'online') == '1' for d in devices):
        return False
    return any(read(d, 'status') == 'Discharging' for d in batteries)


def cpu_busy(threshold: float = 0.7) -> bool:
    """Is the computer already busy (a game, a build)? CPU use above threshold of all cores."""
    try:
        if WINDOWS:
            import ctypes
            from ctypes import wintypes

            def times():
                idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
                ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
                v = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
                return v(idle), v(kernel) + v(user)  # kernel time includes idle time
            i0, t0 = times()
            time.sleep(0.5)
            i1, t1 = times()
            return t1 > t0 and 1 - (i1 - i0) / (t1 - t0) > threshold
        return os.getloadavg()[0] / (os.cpu_count() or 1) > threshold
    except Exception:                                # noqa: BLE001
        return False


def auto_mode(gpus, battery, busy: bool) -> tuple:
    """Video Decoder Auto: -> (mode, why). Efficient on battery, on a busy computer, or without a separate graphics
    chip; High quality on mains power with one."""
    if battery:
        return 'efficient', 'on battery'
    if busy:
        return 'efficient', 'the computer is busy'
    if any(g.discrete for g in gpus):
        return 'high', 'a separate graphics chip on mains power' if battery is False else 'a separate graphics chip'
    if sys.platform == 'darwin':                     # macOS doesn't list its chips; it switches them by itself
        return 'high', 'on mains power'
    return 'efficient', 'a built-in graphics chip'


def known_gpus(config_dir: str, mpv: str, refresh: bool = False) -> list:
    """The graphics chips, detected once per install or update (and mpv), then kept in settings.json. The install
    scripts run `cn-live-viewer check`, which detects them afresh."""
    from . import __version__, settings
    saved = settings.load(config_dir).get('hardware')
    if (not refresh and isinstance(saved, dict) and saved.get('version') == __version__
            and saved.get('mpv') == mpv and isinstance(saved.get('gpus'), list)):
        return from_dicts(saved['gpus'])
    gpus = detect(mpv)
    try:
        settings.save(config_dir, hardware={'version': __version__, 'mpv': mpv, 'gpus': to_dicts(gpus)})
    except OSError:
        pass
    return gpus

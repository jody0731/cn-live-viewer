"""Choices made in the player that carry over to the next start, in settings.json next to the room list."""
import json
import os

# the Video Decoder: Auto picks one of the two modes at each start (hardware.auto_mode); mpv/cnlv.conf has their profiles
MODES = {'efficient': 'Efficient', 'high': 'High quality'}
DECODERS = dict(auto='Auto', **MODES)
# what you set in the player and get back at the next start; Auto choices (quality, Video Decoder) are kept as Auto
DEFAULTS = {'decoder': 'auto', 'quality': 'auto', 'volume': 50, 'mute': False, 'chat': True,
            # the window: fullscreen, maximized, and the size it has when it's neither (% of the screen; None: mpv's)
            'window': {'fullscreen': False, 'maximized': True, 'size': None}}


def path(config_dir: str) -> str:
    return os.path.join(config_dir, 'settings.json')


def load(config_dir: str) -> dict:
    """The settings, with the defaults for anything missing or unreadable."""
    try:
        with open(path(config_dir), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    if 'decoder' not in data and data.get('picture') in MODES:
        data['decoder'] = data['picture']            # 0.11's "Picture" choice, made by hand: kept
    data.pop('picture', None)
    out = dict(DEFAULTS, **data)
    if out['decoder'] not in DECODERS:
        out['decoder'] = DEFAULTS['decoder']
    if not isinstance(out['quality'], str) or not out['quality'].strip():
        out['quality'] = DEFAULTS['quality']
    if isinstance(out['volume'], bool) or not isinstance(out['volume'], (int, float)) or not 0 <= out['volume'] <= 1000:
        out['volume'] = DEFAULTS['volume']
    for key in ('mute', 'chat'):
        if not isinstance(out[key], bool):
            out[key] = DEFAULTS[key]
    out['window'] = window(out['window'])
    return out


def window(w) -> dict:
    """The window settings, each one checked (a bad one gets its default)."""
    w = w if isinstance(w, dict) else {}
    out = dict(DEFAULTS['window'])
    for key in ('fullscreen', 'maximized'):
        if isinstance(w.get(key), bool):
            out[key] = w[key]
    size = w.get('size')
    if (isinstance(size, list) and len(size) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 10 <= v <= 100 for v in size)):
        out['size'] = size
    return out


def save(config_dir: str, **changes) -> None:
    data = load(config_dir)
    data.update(changes)
    os.makedirs(config_dir, exist_ok=True)
    with open(path(config_dir), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
        f.write('\n')

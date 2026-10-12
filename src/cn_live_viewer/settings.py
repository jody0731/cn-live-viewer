"""Choices made in the player that carry over to the next start, in settings.json next to the room list."""
import json
import os

# the Video Decoder: Auto picks one of the two modes at each start (hardware.auto_mode); mpv/cnlv.conf has their profiles
MODES = {'efficient': 'Efficient', 'high': 'High quality'}
DECODERS = dict(auto='Auto', **MODES)
DEFAULTS = {'decoder': 'auto'}


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
    return out


def save(config_dir: str, **changes) -> None:
    data = load(config_dir)
    data.update(changes)
    os.makedirs(config_dir, exist_ok=True)
    with open(path(config_dir), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
        f.write('\n')

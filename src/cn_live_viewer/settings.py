"""Choices made in the player that carry over to the next start, in settings.json next to the room list."""
import json
import os

PICTURES = {'efficient': 'Efficient', 'high': 'High quality'}   # picture modes: mpv/cnlv.conf has their profiles
DEFAULTS = {'picture': 'efficient'}


def path(config_dir: str) -> str:
    return os.path.join(config_dir, 'settings.json')


def load(config_dir: str) -> dict:
    """The settings, with the defaults for anything missing or unreadable."""
    try:
        with open(path(config_dir), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULTS, **(data if isinstance(data, dict) else {}))
    if out['picture'] not in PICTURES:
        out['picture'] = DEFAULTS['picture']
    return out


def save(config_dir: str, **changes) -> None:
    data = load(config_dir)
    data.update(changes)
    os.makedirs(config_dir, exist_ok=True)
    with open(path(config_dir), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
        f.write('\n')

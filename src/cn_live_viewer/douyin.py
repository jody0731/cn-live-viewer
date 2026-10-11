"""Douyin live: stream address and live chat, with a visitor cookie only (no login).

Stream: /webcast/room/web/enter returns the room and its pull addresses; "origin" is the streamer's
original upload. Chat: the polling endpoint /webcast/im/fetch returns protobuf with a cursor; it needs
no request signature (the websocket feed does). See docs/PROTOCOLS.md.
"""
import asyncio
import gzip
import http.cookiejar
import json
import logging
import re
import time
import urllib.parse
import urllib.request

from . import pb
from .quality import Tier

log = logging.getLogger(__name__)
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36'
REFERER = 'https://live.douyin.com/'
COMMON = ('aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&cookie_enabled=true'
          '&screen_width=1920&screen_height=1080&browser_language=zh-CN&browser_platform=Linux'
          '&browser_name=Chrome&browser_version=154.0.0.0')
QUALITIES = ('origin', 'uhd', 'hd', 'sd', 'ld', 'md', 'ao')     # best first; ao is audio only
NAMES = {'origin': 'Original', 'uhd': 'Ultra HD', 'hd': 'HD', 'sd': 'SD', 'ld': 'Low', 'md': 'Smooth', 'ao': 'Audio only'}
GUESS_MBPS = {'origin': 6, 'uhd': 4, 'hd': 2.5, 'sd': 1.2, 'ld': 0.8, 'md': 0.5, 'ao': 0.1}   # when the room doesn't say


def room_id(arg: str) -> str:
    m = re.search(r'(?:live\.douyin\.com/|/live/)(\d+)', arg)
    return m.group(1) if m else arg.strip().split('?')[0].rstrip('/').rsplit('/', 1)[-1]


class Session:
    """A visitor session: the room page sets the ttwid cookie the APIs want."""
    def __init__(self, rid: str):
        self.rid = rid
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.get(f'https://live.douyin.com/{rid}')

    def get(self, url: str, tries: int = 4, rid: str = None) -> bytes:
        """GET with retries, gzip (the room data is ~7x smaller packed) and the room's page as referer."""
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip',
                                                           'Referer': f'https://live.douyin.com/{rid or self.rid}'})
                with self.opener.open(req, timeout=12) as r:
                    body = r.read()
                    return gzip.decompress(body) if r.headers.get('Content-Encoding') == 'gzip' else body
            except OSError:
                if attempt == tries - 1:
                    raise
                time.sleep(1.5 * (attempt + 1))

    def room(self, rid: str = None) -> dict:
        """The room's data: this session's room, or another one (the visitor cookie works for any room)."""
        rid = rid or self.rid
        d = json.loads(self.get(f'https://live.douyin.com/webcast/room/web/enter/?{COMMON}&enter_from=web_live&web_rid={rid}',
                                rid=rid))
        rooms = (d.get('data') or {}).get('data') or []
        if not rooms:
            raise LookupError(f'Douyin room {rid} not found')
        return rooms[0]


def status(rid: str, session: 'Session') -> str:
    """'live' (status 2), 'offline' or 'missing', with an existing session. Raises OSError/ValueError when unknown."""
    try:
        return 'live' if session.room(rid).get('status') == 2 else 'offline'
    except LookupError:
        return 'missing'


def owner_name(room: dict):
    return (room.get('owner') or {}).get('nickname') or None


def streamer_name(rid: str):
    """The streamer's name, live or not. Raises LookupError for an unknown room."""
    return owner_name(Session(rid).room())


def tier(quality: str, main: dict):
    """One quality's level. Its sdk_params usually give the bitrate and resolution."""
    try:
        info = json.loads(main.get('sdk_params') or '{}')
    except ValueError:
        info = {}
    rate = float(info.get('vbitrate') or 0)
    mbps = rate / 1e6 if rate > 1e5 else rate / 1e3 if rate > 100 else GUESS_MBPS.get(quality, 1)
    res = str(info.get('resolution') or '')
    parts = [NAMES.get(quality, quality), f"{res.split('x')[-1]}p" if 'x' in res else '', f'{mbps:.1f} Mbps' if rate else '']
    return Tier(quality, ' · '.join(p for p in parts if p), mbps, main['flv'], video=quality != 'ao')


def streams(rid: str):
    """-> (levels best first, internal room id, streamer name or None). Raises LookupError when the room is not live."""
    room = Session(rid).room()
    if room.get('status') != 2:
        raise LookupError(f'Douyin room {rid} is not live')
    data = json.loads(room['stream_url']['live_core_sdk_data']['pull_data']['stream_data'])['data']
    order = lambda q: QUALITIES.index(q) if q in QUALITIES else len(QUALITIES)
    tiers = [tier(q, data[q]['main']) for q in sorted(data, key=order) if (data[q].get('main') or {}).get('flv')]
    if not tiers:
        raise LookupError(f'Douyin room {rid} has no stream')
    return tiers, room['id_str'], owner_name(room)


def parse_fetch(data: bytes):
    """One /im/fetch response -> ([(msg id, nick, text)], cursor, internal_ext, poll interval seconds)."""
    resp = pb.fields(data)                 # Response: 1 messages, 2 cursor, 3 fetch interval (ms), 5 internal ext
    chats = []
    for raw in resp.get(1, []):
        msg = pb.fields(raw)               # Message: 1 method, 2 payload, 3 msg id
        if pb.text(pb.first(msg, 1)) != 'WebcastChatMessage':
            continue
        body = pb.fields(pb.first(msg, 2, b''))           # ChatMessage: 1 common, 2 user, 3 content
        content = pb.text(pb.first(body, 3)).strip()
        user = pb.fields(pb.first(body, 2, b''))          # User: 3 nickname
        if content:
            chats.append((pb.first(msg, 3, 0), pb.text(pb.first(user, 3), '?'), content))
    interval = max(0.5, min(pb.first(resp, 3, 1000) / 1000, 5))
    return chats, pb.text(pb.first(resp, 2)), pb.text(pb.first(resp, 5)), interval


async def chat(rid: str, internal_id: str = None):
    """Async generator of (nick, text); polls forever."""
    session = await asyncio.to_thread(Session, rid)
    internal_id = internal_id or (await asyncio.to_thread(session.room))['id_str']
    cursor = ext = ''
    seen = set()
    while True:
        url = ('https://live.douyin.com/webcast/im/fetch/?resp_content_type=protobuf&did_rule=3&endpoint=live_pc'
               f'&support_wrds=1&identity=audience&need_persist_msg_count=15&room_id={internal_id}&version_code=180800'
               f'&last_rtt=0&fetch_rule=1&cursor={urllib.parse.quote(cursor)}&internal_ext={urllib.parse.quote(ext)}&{COMMON}')
        wait = 1.0
        try:
            chats, cursor, ext, wait = parse_fetch(await asyncio.to_thread(session.get, url))
            for mid, nick, text in chats:
                if mid not in seen:
                    seen.add(mid)
                    yield nick, text
            if len(seen) > 5000:
                seen = set(list(seen)[-1000:])
        except (OSError, ValueError) as e:
            log.info('Douyin chat fetch failed (%s), retrying', e.__class__.__name__)
            wait = 3
        await asyncio.sleep(wait)

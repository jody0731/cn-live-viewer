"""Huya: stream address and live chat.

Stream: Streamlink's Huya plugin finds the FLV address; the `ratio` parameter selects the bitrate in
kbps, and 20000 is the web player's top "20M" option, which Streamlink does not list on its own.
Chat: a websocket to wss://cdnws.api.huya.com speaking TARS; we register for the room's "live:" and
"chat:" groups and read MessageNotice (uri 1400) pushes. See docs/PROTOCOLS.md.
"""
import asyncio
import json
import logging
import re
import ssl
import time
import urllib.request

import websockets

from . import tars

log = logging.getLogger(__name__)
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
REFERER = 'https://www.huya.com/'
CHAT_WS = 'wss://cdnws.api.huya.com'
DEFAULT_RATIO = 20000


def room_id(arg: str) -> str:
    return arg.split('?')[0].split('#')[0].rstrip('/').rsplit('/', 1)[-1]


def with_ratio(url: str, ratio: int) -> str:
    """Set the bitrate (kbps) Huya serves through the address's `ratio` parameter."""
    if 'ratio=' in url:
        return re.sub(r'([?&])ratio=\d*', rf'\g<1>ratio={ratio}', url)
    return f'{url}{"&" if "?" in url else "?"}ratio={ratio}'


def uid_from_url(url: str):
    """The streamer's id, which Huya puts in the stream path (/src/<uid>-...), or None."""
    m = re.search(r'/src/(\d+)-', url)
    return int(m.group(1)) if m else None


def stream_url(room: str, ratio: int = DEFAULT_RATIO):
    """-> (FLV url, presenter uid or None, streamer name or None). Raises LookupError when the room is offline or unknown."""
    from streamlink import Streamlink
    from streamlink.exceptions import StreamlinkError
    session = Streamlink()
    try:
        _, plugin_class, page = session.resolve_url(f'https://www.huya.com/{room}')
        plugin = plugin_class(session, page)
        streams = plugin.streams()
    except StreamlinkError as e:             # e.g. a room number with no room: Streamlink's page check fails
        log.info('Streamlink: %s', e)
        raise LookupError(f'Huya room {room} is offline or not found') from None
    s = streams.get('hs_source') or streams.get('best')
    if not s or not getattr(s, 'url', None):
        raise LookupError(f'Huya room {room} is offline or not found')
    url = with_ratio(s.url, ratio) if ratio else s.url
    return url, uid_from_url(url), plugin.get_author()


def parse_room_page(html: str):
    """The mobile room page -> (presenter uid, streamer name or None). Raises LookupError when it shows no room."""
    m = re.search(r'"lPresenterUid":(\d+)', html) or re.search(r'"lChannelId":(\d+)', html)
    if not m:
        raise LookupError('no room on the page')
    nick = re.search(r'"sNick":"((?:[^"\\]|\\.)*)"', html)
    try:
        name = json.loads(f'"{nick.group(1)}"') if nick else None
    except ValueError:
        name = None
    return int(m.group(1)), (name or None)


def room_info(room: str):
    """-> (presenter uid, streamer name or None) from the mobile room page; works when the room is offline too."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(5):
        try:
            req = urllib.request.Request(f'https://m.huya.com/{room}', headers={'User-Agent': UA})
            html = opener.open(req, timeout=10).read().decode('utf-8', 'replace')
        except OSError as e:
            log.info('room lookup failed (%s), retrying', e.__class__.__name__)
            time.sleep(2 + 2 * attempt)
            continue
        try:
            return parse_room_page(html)
        except LookupError:
            raise LookupError(f'Huya room {room} not found') from None
    raise LookupError(f'could not reach Huya to look up room {room}')


def register_frame(uid: int) -> bytes:
    """WebSocketCommand(16 = RegisterGroupReq, WSRegisterGroupReq([live:uid, chat:uid], token ''))."""
    req = tars.string_list(0, [f'live:{uid}', f'chat:{uid}']) + tars.string(1, '')
    return tars.int_(0, 16) + tars.bytes_(1, req)


HEARTBEAT = tars.int_(0, 5)


def parse_frame(data: bytes):
    """Chat messages in one websocket frame -> [(nick, text)]."""
    out = []
    cmd = tars.decode(data)
    if cmd.get(0) not in (7, 22) or not isinstance(cmd.get(1), (bytes, bytearray)):
        return out
    push = tars.decode(cmd[1])
    if cmd[0] == 22:                                   # WSPushMessage_V2: group id, [WSMsgItem(uri, msg)]
        items = push.get(1) or []
    else:                                              # WSPushMessage: push type, uri, msg
        items = [{0: push.get(1), 1: push.get(2)}]
    for it in items:
        if isinstance(it, dict) and it.get(0) == 1400 and isinstance(it.get(1), (bytes, bytearray)):
            msg = tars.decode(it[1])                   # MessageNotice: sender info, tid, sid, content
            user = msg.get(0) if isinstance(msg.get(0), dict) else {}
            text = msg.get(3)
            if isinstance(text, str) and text.strip():
                out.append((str(user.get(2, '?')), text.strip()))
    return out


async def chat(room: str, uid: int = None):
    """Async generator of (nick, text); reconnects forever."""
    uid = uid or (await asyncio.to_thread(room_info, room))[0]
    while True:
        try:
            async with websockets.connect(CHAT_WS, ssl=ssl.create_default_context(), user_agent_header=UA,
                                          ping_interval=None, max_size=None, proxy=None) as ws:
                await ws.send(register_frame(uid))

                async def beat():
                    while True:
                        await asyncio.sleep(30)
                        await ws.send(HEARTBEAT)
                hb = asyncio.create_task(beat())
                try:
                    async for frame in ws:
                        if isinstance(frame, bytes):
                            try:
                                for item in parse_frame(frame):
                                    yield item
                            except (ValueError, IndexError):
                                pass                   # an unknown message shape; skip it
                finally:
                    hb.cancel()
        except (OSError, websockets.WebSocketException) as e:
            log.info('Huya chat dropped (%s), reconnecting', e.__class__.__name__)
            await asyncio.sleep(3)

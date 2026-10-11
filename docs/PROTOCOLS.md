# Protocols

How cn-live-viewer gets each site's stream and chat. Everything here was observed from the sites' own web players
on 2026-10-10; the sites can change it at any time. No login is used anywhere.

## Huya

### Stream address

Streamlink's Huya plugin reads the room page and returns FLV addresses. cn-live-viewer takes `hs_source` (or `best`)
and sets the bitrate through the address's `ratio` parameter, in kbps:

```
https://<cdn>/src/<uid>-<uid>-<n>.flv?wsSecret=...&wsTime=...&ratio=20000&...
```

- `ratio=20000` is the web player's top option (20 Mbps). Streamlink only lists streams up to about 8 Mbps.
- The number after `/src/` is the streamer's id (presenter uid). It is the chat's group id, so the room page doesn't
  have to be fetched again.
- mpv must send `Referer: https://www.huya.com/`.

### Chat

A binary websocket to `wss://cdnws.api.huya.com`. Every frame is a TARS struct (see below).

| Step | Frame |
|---|---|
| Join | `WebSocketCommand{0: 16 (RegisterGroupReq), 1: WSRegisterGroupReq{0: ["live:<uid>", "chat:<uid>"], 1: ""}}` |
| Keep alive | `WebSocketCommand{0: 5}` every 30 s |
| Push (old) | `WebSocketCommand{0: 7, 1: WSPushMessage{0: push type, 1: uri, 2: message bytes}}` |
| Push (new) | `WebSocketCommand{0: 22, 1: WSPushMessage_V2{0: group id, 1: [WSMsgItem{0: uri, 1: message bytes}]}}` |

Text chat is uri **1400**, `MessageNotice`:

| Tag | Field |
|---|---|
| 0 | sender info (struct; tag 2 is the nickname) |
| 1, 2 | channel ids |
| 3 | message text |

Gifts, entry notices and everything else use other uris and are skipped.

### Streamer name

When a room is live, Streamlink reports the streamer's name. For adding a room, which may be offline, the mobile
room page `https://m.huya.com/<room>` has it as `"sNick"`, next to the streamer's id (`"lPresenterUid"`).

### TARS in brief

Each field is a head byte followed by its value.
- **Head byte:** the field tag is the high nibble and the type is the low nibble.
- **Tag 15:** the real tag is in the next byte.

| Type | Meaning |
|---|---|
| 0, 1, 2, 3 | int8, int16, int32, int64 (big-endian) |
| 4, 5 | float, double |
| 6 | string, 1-byte length |
| 7 | string, 4-byte length |
| 8 | map: an int count, then key/value pairs |
| 9 | list: an int count, then values |
| 10, 11 | struct begin, struct end |
| 12 | zero (an int that is 0, no payload) |
| 13 | bytes: an element-type head (int8), an int length, the bytes |

[`tars.py`](../src/cn_live_viewer/tars.py) implements the codec.

## Douyin

All requests carry a browser User-Agent and only the visitor cookie `ttwid`, which `https://live.douyin.com/<room>`
sets on the first visit. Each request also carries the web player's fixed parameters (`aid=6383`,
`app_name=douyin_web`, ...; see `COMMON` in [`douyin.py`](../src/cn_live_viewer/douyin.py)).

### Stream address

`GET https://live.douyin.com/webcast/room/web/enter/?<common>&enter_from=web_live&web_rid=<room>`

From `data.data[0]`:
- `status`: 2 means live.
- `id_str`: the internal room id the chat needs. It differs from the number in the address.
- `stream_url.live_core_sdk_data.pull_data.stream_data`: a JSON string. Its `data` has one entry per quality
  (`origin`, `hd`, `sd`, `ld`, `md`), each with `main.flv` and `main.hls`.

`origin` is the streamer's own upload. mpv must send `Referer: https://live.douyin.com/`.

`owner.nickname` is the streamer's name, given whether the room is live or not.

### Chat

Douyin's websocket feed needs a signed request. The polling endpoint does not, so cn-live-viewer polls it:

`GET https://live.douyin.com/webcast/im/fetch/?resp_content_type=protobuf&room_id=<id_str>&cursor=<c>&internal_ext=<e>&...`

The reply is protobuf. The field numbers cn-live-viewer reads:

| Message | Field | Meaning |
|---|---|---|
| Response | 1 | messages (repeated `Message`) |
| | 2 | cursor for the next poll |
| | 3 | poll again after this many ms |
| | 5 | `internal_ext` for the next poll |
| Message | 1 | method, e.g. `WebcastChatMessage` |
| | 2 | payload |
| | 3 | message id (used to drop repeats) |
| ChatMessage | 2 | user (`User`, field 3 is the nickname) |
| | 3 | message text |

The first poll has an empty cursor and returns the last few messages. Later polls return what's new since the
cursor. [`pb.py`](../src/cn_live_viewer/pb.py) reads the wire format without `.proto` files.

## cn-live-viewer and its mpv scripts

cn-live-viewer starts mpv with `--input-ipc-server=<socket>` (a named pipe, `\\.\pipe\...`, on Windows) and loads its three Lua scripts with `--script=`. They
talk through `script-message`:

| Message | From → to | Meaning |
|---|---|---|
| `cnlv-danmaku <text>` | controller → danmaku.lua | add one chat message to the overlay |
| `cnlv-danmaku-clear` | controller → danmaku.lua | clear the overlay (on room switch) |
| `cnlv-switch <platform> <room>` | picker.lua → controller | play that room |
| `cnlv-save` | picker.lua → controller | save the current room to the list |
| `cnlv-add <text>` | picker.lua → controller | look up a room number or link and add it |
| `cnlv-rename <platform> <room> <name>` | picker.lua → controller | rename a saved room |
| `cnlv-remove <platform> <room>` | picker.lua → controller | remove a saved room |
| `cnlv-default <platform> <room>` | picker.lua → controller | move a saved room to the top of the list, which makes it the default |

The three scripts:
- **danmaku.lua** draws the chat. It publishes whether the overlay is on in the property `user-data/cnlv/chat`.
- **picker.lua** handles the room list (Tab) and fills mpv's right-click menu (`menu-data`).
  It reads the rooms from the property `user-data/cnlv/rooms`, which the controller keeps current:
  `{"playing": bool, "rooms": [...]}` with the current room marked. A property rather than a message,
  so the list is there whenever the script loads.
- **bar.lua** is the control bar. Its buttons call the other two through `script-binding picker/cnlv-picker` and
  `script-binding danmaku/cnlv-toggle-danmaku`.

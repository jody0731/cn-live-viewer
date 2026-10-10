"""Minimal protobuf reader, enough for Douyin's chat feed (no .proto files needed).

fields(data) returns {field number: [values]}: varints as int, length-delimited fields as bytes
(nested messages are decoded by calling fields() again on those bytes).
"""


def varint(data: bytes, i: int):
    value = shift = 0
    while True:
        if i >= len(data):
            raise ValueError('truncated varint')
        x = data[i]
        i += 1
        value |= (x & 0x7F) << shift
        shift += 7
        if x < 0x80:
            return value, i


def fields(data: bytes) -> dict:
    out, i = {}, 0
    while i < len(data):
        key, i = varint(data, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = varint(data, i)
        elif wire == 2:
            n, i = varint(data, i)
            value = data[i:i + n]
            i += n
        elif wire == 1:
            value = data[i:i + 8]
            i += 8
        elif wire == 5:
            value = data[i:i + 4]
            i += 4
        else:
            break                                  # groups (3/4) are not used by Douyin
        out.setdefault(number, []).append(value)
    return out


def first(msg: dict, number: int, default=None):
    v = msg.get(number)
    return v[0] if v else default


def text(value, default: str = '') -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode('utf-8', 'replace')
    return default if value is None else str(value)

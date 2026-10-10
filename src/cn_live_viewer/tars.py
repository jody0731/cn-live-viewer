"""Minimal TARS codec (Tencent's binary serialisation), enough for Huya's web chat.

A TARS value is a one-byte head (tag in the high nibble, type in the low nibble; tag 15 means "the
real tag follows in the next byte") followed by the payload. Structs are just a run of tagged
fields, so a decoded struct is a dict {tag: value}.
"""
import struct

INT8, INT16, INT32, INT64, FLOAT, DOUBLE, STR1, STR4, MAP, LIST, STRUCT_BEGIN, STRUCT_END, ZERO, SIMPLE_LIST = range(14)


# ---------------------------------------------------------------- encoding
def head(tag: int, typ: int) -> bytes:
    return bytes([(tag << 4) | typ]) if tag < 15 else bytes([0xF0 | typ, tag])


def int_(tag: int, value: int) -> bytes:
    if value == 0:
        return head(tag, ZERO)
    for typ, fmt, lo, hi in ((INT8, '>b', -2**7, 2**7 - 1), (INT16, '>h', -2**15, 2**15 - 1),
                             (INT32, '>i', -2**31, 2**31 - 1)):
        if lo <= value <= hi:
            return head(tag, typ) + struct.pack(fmt, value)
    return head(tag, INT64) + struct.pack('>q', value)


def string(tag: int, value: str) -> bytes:
    b = value.encode()
    if len(b) < 256:
        return head(tag, STR1) + bytes([len(b)]) + b
    return head(tag, STR4) + struct.pack('>I', len(b)) + b


def bytes_(tag: int, value: bytes) -> bytes:
    return head(tag, SIMPLE_LIST) + head(0, INT8) + int_(0, len(value)) + value


def string_list(tag: int, values) -> bytes:
    return head(tag, LIST) + int_(0, len(values)) + b''.join(string(0, v) for v in values)


def struct_(tag: int, body: bytes) -> bytes:
    return head(tag, STRUCT_BEGIN) + body + head(0, STRUCT_END)


# ---------------------------------------------------------------- decoding
class Reader:
    def __init__(self, data: bytes):
        self.b, self.i = data, 0

    def _head(self):
        x = self.b[self.i]
        self.i += 1
        tag, typ = x >> 4, x & 15
        if tag == 15:
            tag = self.b[self.i]
            self.i += 1
        return tag, typ

    def _take(self, n: int) -> bytes:
        v = self.b[self.i:self.i + n]
        if len(v) < n:
            raise ValueError('truncated TARS data')
        self.i += n
        return v

    def _int(self) -> int:
        _, typ = self._head()
        return self._value(typ)

    def _value(self, typ: int):
        if typ == ZERO:
            return 0
        if typ == INT8:
            return struct.unpack('>b', self._take(1))[0]
        if typ == INT16:
            return struct.unpack('>h', self._take(2))[0]
        if typ == INT32:
            return struct.unpack('>i', self._take(4))[0]
        if typ == INT64:
            return struct.unpack('>q', self._take(8))[0]
        if typ == FLOAT:
            return struct.unpack('>f', self._take(4))[0]
        if typ == DOUBLE:
            return struct.unpack('>d', self._take(8))[0]
        if typ == STR1:
            return self._take(self._take(1)[0]).decode('utf-8', 'replace')
        if typ == STR4:
            return self._take(struct.unpack('>I', self._take(4))[0]).decode('utf-8', 'replace')
        if typ == MAP:
            out = {}
            for _ in range(self._int()):
                k = self._value(self._head()[1])
                out[k] = self._value(self._head()[1])
            return out
        if typ == LIST:
            return [self._value(self._head()[1]) for _ in range(self._int())]
        if typ == STRUCT_BEGIN:
            out = {}
            while True:
                tag, t = self._head()
                if t == STRUCT_END:
                    return out
                out[tag] = self._value(t)
        if typ == SIMPLE_LIST:
            self._head()                         # element type (always INT8 = bytes)
            return self._take(self._int())
        raise ValueError(f'unknown TARS type {typ}')

    def struct(self) -> dict:
        out = {}
        while self.i < len(self.b):
            tag, typ = self._head()
            if typ == STRUCT_END:
                break
            out[tag] = self._value(typ)
        return out


def decode(data: bytes) -> dict:
    """Decode a top-level TARS struct into {tag: value}."""
    return Reader(data).struct()

"""In-process Filang engine. No background worker or external runtime."""

import ctypes
import json
from functools import lru_cache
from pathlib import Path
from struct import Struct
from threading import Lock

__all__ = ["Engine", "FilangError"]
_BAR = Struct("<B7d")
_ABI = 1


class FilangError(ValueError):
    """An invalid Filang request or input."""


@lru_cache(maxsize=1)
def _library():
    files = list(Path(__file__).parent.glob("_filang_engine.*"))
    if len(files) != 1:
        raise ImportError("Filang native library is missing from this wheel")
    lib = ctypes.CDLL(str(files[0]))
    sig = {
        "filang_abi_version": (ctypes.c_uint32, ()),
        "filang_session_new": (ctypes.c_void_p, ()),
        "filang_session_drop": (None, (ctypes.c_void_p,)),
        "filang_call": (
            ctypes.c_uint32,
            (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t),
        ),
        "filang_output": (ctypes.c_void_p, (ctypes.c_void_p,)),
        "filang_output_len": (ctypes.c_size_t, (ctypes.c_void_p,)),
    }
    for name, (returns, args) in sig.items():
        symbol = getattr(lib, name)
        symbol.restype = returns
        symbol.argtypes = args
    if lib.filang_abi_version() != _ABI:
        raise ImportError("unsupported Filang engine ABI")
    return lib


def _mode(oriented):
    return "oriented" if oriented else "unoriented"


def _fields(*values):
    return "\t".join(map(str, values))


class Engine:
    """A recording and prepared windows. Calls within a session are serialized."""

    def __init__(self):
        self._lock = Lock()
        self._lib = _library()
        self._handle = self._lib.filang_session_new()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._lock:
            if getattr(self, "_handle", None):
                self._lib.filang_session_drop(self._handle)
                self._handle = None

    def __del__(self):
        self.close()

    def version(self):
        return self._call("version")

    def catalogue(self):
        return self._call("catalogue")

    def inspect(self, code):
        return self._call("inspect", code)

    def distance(self, left, right):
        return self._call("distance", _fields(left, right))

    def domain(self, width, *, oriented=True, dimensions=()):
        return self._call("domain", _fields(width, _mode(oriented), ",".join(dimensions)))

    def load(self, bars):
        """Load OHLC rows, optionally followed by USDT volume, taker-buy USDT, and trades."""
        data = bytearray()
        for slot, bar in enumerate(bars):
            if slot >= 1_000_000:
                raise FilangError("Filang recording exceeds 1,000,000 slots")
            if bar is None:
                data.extend(bytes(_BAR.size))
            elif len(bar) == 4:
                data.extend(_BAR.pack(1, *bar, 0, 0, 0))
            elif len(bar) == 7:
                data.extend(_BAR.pack(2, *bar))
            else:
                raise FilangError(f"invalid Filang bar at slot {slot}")
        return self._call("load", data)

    def load_csv(self, csv, interval_ms, *, instrument="BTCUSDT"):
        return self._call("load-csv", f"{_fields(interval_ms, instrument)}\n{csv}")

    def set_calendar(self, tsv="", *, table=None):
        if table is None:
            return self._call("calendar", tsv)
        return self._call("calendar-named", f"{table}\n{tsv}")

    def install_definition(self, text, sha256):
        return self._call("install-definition", f"{sha256}\n{text}")

    def check(self, query):
        return self._call("check", query)

    def study(self, query, *, candidate=None):
        index = "-" if candidate is None else str(candidate)
        return self._call("study", f"{index}\n{query}")

    def prepare(self, width, *, oriented=True, reading="recorded", dimensions=()):
        return self._call(
            "prepare", _fields(width, _mode(oriented), reading, ",".join(dimensions))
        )

    def release(self, width):
        return self._call("release", str(width))

    def at(self, end, width, *, oriented=True, reading="recorded", dimensions=()):
        return self._call(
            "at", _fields(end, width, _mode(oriented), reading, ",".join(dimensions))
        )

    def draw(self, bars, *, oriented=True, reading="recorded", axes=None):
        return self._drawing("draw", bars, oriented, reading, axes)

    def draw_counts(self, bars, *, oriented=True, reading="recorded", axes=None):
        return self._drawing("draw-counts", bars, oriented, reading, axes)

    def _drawing(self, operation, bars, oriented, reading, axes):
        rows = [_fields(_mode(oriented), reading, len(bars))]
        rows.extend(_fields(*row) for row in bars)
        rows.extend(_fields(axis, *marks) for axis, marks in (axes or {}).items())
        return self._call(operation, "\n".join(rows))

    def drawing_protocol(self):
        return self._call("drawing-protocol")

    def decode_drawing(self, packet, expected_code=""):
        return self._call("read-drawing", f"{expected_code}\n{packet}")

    def encode_drawing(self, packet):
        protocol = self.drawing_protocol()
        key = "dimensioned" if packet.get("dimensions") else "plain"
        marked = {**packet, "version": protocol["version"], "revision": protocol[key]}
        if key == "plain":
            marked.pop("dimensions", None)
        text = json.dumps(marked, ensure_ascii=False, separators=(",", ":"))
        self.decode_drawing(text)
        return text

    def counts(self, code, *, reading="recorded"):
        return self._call("counts", _fields(reading, code))

    def positions(self, code, *, reading="recorded", start=0, limit=100):
        return self._call("positions", _fields(reading, start, limit, code))

    def classify(self, code, *, reading="recorded", start=0, limit=4096):
        return self._call("classify", _fields(reading, start, limit, code))

    def _call(self, operation, payload=b""):
        with self._lock:
            if not self._handle:
                raise FilangError("Filang engine is closed")
            if isinstance(payload, str):
                payload = payload.encode()
            request = (operation + "\n").encode() + payload
            status = self._lib.filang_call(self._handle, request, len(request))
            out = self._lib.filang_output(self._handle)
            size = self._lib.filang_output_len(self._handle)
            value = ctypes.string_at(out, size).decode()
            if status:
                raise FilangError(value)
            return json.loads(value)

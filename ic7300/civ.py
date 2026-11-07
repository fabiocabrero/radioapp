"""Protocolo CI-V da Icom: BCD, quadros e comandos do IC-7300."""
from __future__ import annotations

from dataclasses import dataclass

PREAMBLE = b"\xfe\xfe"
EOM = 0xFD
ACK = 0xFB
NAK = 0xFA

IC7300_ADDRESS = 0x94
CONTROLLER_ADDRESS = 0xE0

# Comandos principais
CMD_FREQ_NOTIFY = 0x00
CMD_MODE_NOTIFY = 0x01
CMD_READ_FREQ = 0x03
CMD_READ_MODE = 0x04
CMD_SET_FREQ = 0x05
CMD_SET_MODE = 0x06
CMD_LEVEL = 0x14
CMD_METER = 0x15
CMD_FUNC = 0x16
CMD_SEND_CW = 0x17
CMD_READ_ID = 0x19
CMD_MENU = 0x1A
CMD_TRANSMIT = 0x1C
CMD_SCOPE = 0x27

# Modos do IC-7300
MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x07: "CW-R", 0x08: "RTTY-R"}
MODE_CODES = {name: code for code, name in MODES.items()}

# Subcomandos de nível (0x14)
LEVELS = {"af": 0x01, "rf": 0x02, "sql": 0x03, "nr": 0x06, "pbt1": 0x07, "pbt2": 0x08,
          "cw_pitch": 0x09, "power": 0x0A, "mic": 0x0B, "key_speed": 0x0C, "comp": 0x0E, "nb": 0x12}
# Subcomandos de medidor (0x15)
METERS = {"s": 0x02, "po": 0x11, "swr": 0x12, "alc": 0x13}
# Subcomandos de função (0x16)
FUNCS = {"preamp": 0x02, "agc": 0x12, "nb": 0x22, "nr": 0x40, "anf": 0x41, "comp": 0x44}

# Scope (0x27)
SCOPE_WAVE = 0x00
SCOPE_ON_OFF = 0x10
SCOPE_WAVE_OUTPUT = 0x11
SCOPE_MODE = 0x14
SCOPE_SPAN = 0x15
SCOPE_DIVISIONS = 11
SCOPE_POINTS = 475
SCOPE_SPANS_HZ = [2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000]


def freq_to_bcd(hz: int) -> bytes:
    """Frequência em Hz -> 5 bytes BCD, byte menos significativo primeiro."""
    out = bytearray()
    for _ in range(5):
        out.append(((hz // 10) % 10) << 4 | (hz % 10))
        hz //= 100
    return bytes(out)


def bcd_to_freq(data: bytes) -> int:
    hz = 0
    for i, b in enumerate(data[:5]):
        hz += ((b >> 4) * 10 + (b & 0x0F)) * 100 ** i
    return hz


def int_to_bcd(value: int, nbytes: int = 2) -> bytes:
    """Número -> BCD com o dígito mais significativo primeiro (níveis 0000-0255)."""
    digits = f"{max(0, value):0{nbytes * 2}d}"[-nbytes * 2:]
    return bytes(int(digits[i]) << 4 | int(digits[i + 1]) for i in range(0, len(digits), 2))


def bcd_to_int(data: bytes) -> int:
    value = 0
    for b in data:
        value = value * 100 + (b >> 4) * 10 + (b & 0x0F)
    return value


@dataclass
class Frame:
    dst: int
    src: int
    payload: bytes  # comando + subcomando + dados

    @property
    def cmd(self) -> int:
        return self.payload[0] if self.payload else -1

    @property
    def data(self) -> bytes:
        return self.payload[1:]

    def encode(self) -> bytes:
        return PREAMBLE + bytes([self.dst, self.src]) + self.payload + bytes([EOM])


class FrameParser:
    """Remonta quadros CI-V a partir de um fluxo de bytes."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        self._buf.extend(chunk)
        frames: list[Frame] = []
        while True:
            start = self._buf.find(PREAMBLE)
            if start < 0:
                del self._buf[:-1]  # guarda um possível 0xFE incompleto
                break
            if start:
                del self._buf[:start]
            end = self._buf.find(bytes([EOM]), 2)
            if end < 0:
                break
            body = bytes(self._buf[2:end])
            del self._buf[: end + 1]
            body = body.lstrip(b"\xfe")  # preâmbulo extra
            if len(body) >= 3:
                frames.append(Frame(body[0], body[1], body[2:]))
        return frames


def build(dst: int, src: int, payload: bytes) -> bytes:
    return Frame(dst, src, payload).encode()


@dataclass
class ScopeLine:
    """Uma linha completa do scope (475 pontos, amplitude 0-160)."""
    mode: int          # 0 = centrado, 1 = fixo
    low_hz: int
    high_hz: int
    out_of_range: bool
    values: bytes


class ScopeAssembler:
    """Junta as 11 divisões de uma varredura do scope do IC-7300."""

    def __init__(self) -> None:
        self._parts: dict[int, bytes] = {}
        self._header: tuple[int, int, int, bool] | None = None

    def feed(self, data: bytes) -> ScopeLine | None:
        """`data` é o conteúdo após o comando 0x27 e o subcomando 0x00."""
        # O manual traz um byte de receptor (00) antes da divisão; aceita com ou sem ele.
        if len(data) >= 3 and data[0] == 0x00 and data[2] == 0x11 and 1 <= bcd_to_int(data[1:2]) <= 11:
            off = 1
        elif len(data) >= 2 and data[1] == 0x11 and 1 <= bcd_to_int(data[0:1]) <= 11:
            off = 0
        else:
            return None
        seq = bcd_to_int(data[off:off + 1])
        total = bcd_to_int(data[off + 1:off + 2])
        body = data[off + 2:]
        if seq == 1:
            self._parts.clear()
            if len(body) < 12:
                return None
            self._header = (body[0], bcd_to_freq(body[1:6]), bcd_to_freq(body[6:11]), bool(body[11]))
            body = body[12:]
        elif self._header is None:
            return None
        self._parts[seq] = bytes(body)
        if seq == total and len(self._parts) == total:
            mode, a, b, oor = self._header
            # modo centrado (0): frequência central e meia-largura; modo fixo (1): bordas baixa e alta (visto no IC-7300 real)
            low, high = (a - b, a + b) if mode == 0 else (a, b)
            values = b"".join(self._parts[i] for i in range(1, total + 1))
            self._header = None
            self._parts.clear()
            return ScopeLine(mode, low, high, oor, values)
        return None

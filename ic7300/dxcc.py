"""Identificação de DXCC a partir de indicativo, usando o cty.dat (AD1C)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_CTY = Path(__file__).parent / "data" / "cty.dat"

_OVERRIDE_RE = re.compile(r"\((\d+)\)|\[(\d+)\]|<[^>]*>|\{[^}]*\}|~[^~]*~")
_IGNORED_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "LGT", "T", "R"}


@dataclass
class Entity:
    name: str
    cq: int
    itu: int
    continent: str
    lat: float
    lon: float  # leste positivo (o cty.dat usa oeste positivo)
    tz: float
    prefix: str


class Cty:
    def __init__(self, path: Path = DEFAULT_CTY) -> None:
        self.prefixes: dict[str, Entity] = {}
        self.exact: dict[str, Entity] = {}
        self._load(path)
        self._max_len = max(len(p) for p in self.prefixes)

    def _load(self, path: Path) -> None:
        text = path.read_text(encoding="latin-1")
        for block in text.split(";"):
            lines = block.strip().splitlines()
            if not lines:
                continue
            head = lines[0].split(":")
            if len(head) < 8:
                continue
            ent = Entity(head[0].strip(), int(head[1]), int(head[2]), head[3].strip(),
                         float(head[4]), -float(head[5]), float(head[6]), head[7].strip().lstrip("*"))
            for item in ",".join(lines[1:]).split(","):
                item = item.strip()
                if not item:
                    continue
                exact = item.startswith("=")
                token = item.lstrip("=")
                m = _OVERRIDE_RE.search(token)
                over = Entity(**ent.__dict__)
                for om in _OVERRIDE_RE.finditer(token):
                    if om.group(1):
                        over.cq = int(om.group(1))
                    elif om.group(2):
                        over.itu = int(om.group(2))
                token = _OVERRIDE_RE.sub("", token) if m else token
                (self.exact if exact else self.prefixes)[token.upper()] = over

    def lookup(self, call: str) -> Optional[Entity]:
        call = call.strip().upper()
        if not call:
            return None
        if call in self.exact:
            return self.exact[call]
        parts = [p for p in call.split("/") if p]
        if len(parts) > 1:
            parts = [p for p in parts if p not in _IGNORED_SUFFIXES and not p.isdigit()] or parts[:1]
            call = min(parts, key=len) if len(parts) == 2 and len(min(parts, key=len)) <= 4 else max(parts, key=len)
        if call in self.exact:
            return self.exact[call]
        for n in range(min(len(call), self._max_len), 0, -1):
            ent = self.prefixes.get(call[:n])
            if ent:
                return ent
        return None

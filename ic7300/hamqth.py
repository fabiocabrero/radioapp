"""Consulta de indicativo no HamQTH (callbook XML). Exige conta gratuita do próprio usuário (usuário e senha)."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

URL = "https://www.hamqth.com/xml.php"
PROGRAM = "IC7300App"
FIELDS = ("callsign", "nick", "adr_name", "qth", "adr_city", "country", "continent", "grid", "latitude", "longitude",
          "cq", "itu", "iota", "us_state", "qsl_via", "lotw", "eqsl", "lic_year", "web", "utc_offset")


class HamQTHError(Exception):
    pass


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_session(xml_text: str) -> str:
    root = _strip_ns(ET.fromstring(xml_text))
    sid = root.findtext(".//session_id")
    if not sid:
        raise HamQTHError(root.findtext(".//error") or "Resposta sem session_id")
    return sid.strip()


def parse_callsign(xml_text: str) -> dict:
    root = _strip_ns(ET.fromstring(xml_text))
    err = root.findtext(".//error")
    if err:
        raise HamQTHError(err.strip())
    search = root.find(".//search")
    if search is None:
        raise HamQTHError("Resposta sem dados")
    return {f: (search.findtext(f) or "").strip() for f in FIELDS if (search.findtext(f) or "").strip()}


class HamQTH:
    def __init__(self, user: str = "", password: str = "") -> None:
        self.user, self.password = user, password
        self._sid, self._sid_time = "", 0.0

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    def _get(self, params: dict, timeout: float = 15) -> str:
        req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": PROGRAM + "/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def lookup(self, call: str) -> dict:
        if not self.configured:
            raise HamQTHError("Informe usuário e senha do HamQTH.")
        for attempt in (0, 1):
            if not self._sid or time.time() - self._sid_time > 3000:  # a sessão vale 1 hora
                self._sid = parse_session(self._get({"u": self.user, "p": self.password}))
                self._sid_time = time.time()
            try:
                return parse_callsign(self._get({"id": self._sid, "callsign": call.lower(), "prg": PROGRAM}))
            except HamQTHError as exc:
                if attempt == 0 and "Session" in str(exc):
                    self._sid = ""
                    continue
                raise
        raise HamQTHError("Falha na consulta")

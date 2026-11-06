"""Programas externos de modos digitais e Winlink: detecção no PC, abertura e orientação de ligação ao rádio.

VARA, VarAC e Winlink Express são programas de terceiros (VARA e VarAC são proprietários): o app não os reimplementa,
só detecta, abre e explica como compartilhar o rádio com eles pelo servidor rigctl (Hamlib NET rigctl).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RIGCTL_ADDRESS = "127.0.0.1:4532"
SOUNDCARD = "USB Audio CODEC"


@dataclass(frozen=True)
class ExtApp:
    key: str
    name: str
    group: str
    summary: str
    exe: tuple[str, ...]
    globs: tuple[str, ...]
    url: str
    needs_rigctl: bool = False
    tips: tuple[str, ...] = ()


GROUPS = ("Winlink e e-mail por rádio", "Modos digitais", "Logs e concursos")

APPS: tuple[ExtApp, ...] = (
    ExtApp("winlink_express", "Winlink Express", GROUPS[0],
           "Cliente oficial do Winlink: e-mail por rádio via VARA HF, ARDOP e Packet.",
           ("RMS Express.exe",), ("C:/Program Files*/RMS Express/RMS Express.exe",), "https://winlink.org/WinlinkExpress",
           tips=("Cadastre seu indicativo no Winlink (gratuito) para ter a conta de e-mail.",
                 f"Placa de som: {SOUNDCARD}. O controle do rádio é feito pelo próprio programa (porta COM do IC-7300) "
                 "ou, se a sua versão oferecer Hamlib, pelo servidor rigctl deste app.")),
    ExtApp("pat", "Pat (Winlink de código aberto)", GROUPS[0],
           "Cliente Winlink gratuito com interface web; fala com VARA HF, ARDOP e Packet.",
           ("pat.exe",), ("C:/Program Files*/Pat/pat.exe", "C:/pat/pat.exe", "%LOCALAPPDATA%/Programs/pat/pat.exe"),
           "https://getpat.io/", needs_rigctl=True,
           tips=("A interface abre no navegador (porta 8080, por padrão).",
                 f"Controle do rádio: configure o rig como Hamlib e aponte para {RIGCTL_ADDRESS} (servidor rigctl deste app).")),
    ExtApp("vara_hf", "VARA HF", GROUPS[0],
           "Modem HF de alto desempenho (EA5HVK) usado pelo Winlink Express, Pat e VarAC. Proprietário: a versão sem registro é limitada em velocidade.",
           ("VARA.exe",), ("C:/VARA/VARA.exe", "C:/VARA HF/VARA.exe", "C:/Program Files*/VARA/VARA.exe", "C:/Program Files*/VARA HF/VARA.exe"),
           "https://rosmodem.wordpress.com/",
           tips=(f"Em Settings, placa de som: {SOUNDCARD} (entrada e saída); ajuste o nível para o ALC não acionar.",
                 "O modem oferece as portas TCP 8300 (comandos) e 8301 (dados) em 127.0.0.1 para Winlink Express, Pat e VarAC.",
                 "Só um programa deve comandar o PTT do rádio.")),
    ExtApp("ardopcf", "ARDOP (ardopcf)", GROUPS[0],
           "Modem ARDOP gratuito e de código aberto, usado pelo Pat e pelo Winlink Express.",
           ("ardopcf.exe", "ardopc.exe"), ("C:/ardopcf/ardopcf.exe", "C:/ardop/ardopcf.exe", "C:/Program Files*/ardopcf/ardopcf.exe"),
           "https://github.com/pflarue/ardop",
           tips=(f"Use o {SOUNDCARD} como entrada e saída.",)),
    ExtApp("varac", "VarAC", GROUPS[0],
           "Chat e mensagens curtas sobre o VARA HF, com CQ automático e agenda de contatos. Proprietário (gratuito para uso pessoal).",
           ("VarAC.exe",), ("C:/VarAC/VarAC.exe", "C:/Program Files*/VarAC/VarAC.exe", "%LOCALAPPDATA%/VarAC/VarAC.exe",
                            "%LOCALAPPDATA%/Programs/VarAC/VarAC.exe"),
           "https://www.varac-hamradio.com/",
           tips=("Precisa do VARA HF instalado e aberto (o VarAC fala com ele pelas portas 8300/8301).",
                 f"Controle do rádio: escolha a porta COM do IC-7300 ou Hamlib apontando para {RIGCTL_ADDRESS}. Use só um dos dois ao mesmo tempo.")),
    ExtApp("wsjtx", "WSJT-X", GROUPS[1],
           "FT8, FT4, WSPR, JT65, FST4, Q65 e outros modos fracos.",
           ("wsjtx.exe",), ("C:/WSJT/wsjtx/bin/wsjtx.exe", "C:/Program Files*/wsjt/wsjtx/bin/wsjtx.exe", "C:/Program Files*/WSJT-X/bin/wsjtx.exe"),
           "https://wsjt.sourceforge.io/", needs_rigctl=True,
           tips=(f"Settings > Radio: Rig = Hamlib NET rigctl, Network Server = {RIGCTL_ADDRESS}, PTT = CAT, Mode = Data/Pkt.",
                 f"Settings > Audio: {SOUNDCARD}. Não transmita ao mesmo tempo que o FT8 deste app.")),
    ExtApp("jtdx", "JTDX", GROUPS[1], "Variante do WSJT-X para FT8/FT4 com decodificação reforçada.",
           ("jtdx.exe",), ("C:/JTDX*/jtdx.exe", "C:/JTDX*/bin/jtdx.exe", "C:/Program Files*/JTDX*/jtdx.exe"),
           "https://www.jtdx.tech/", needs_rigctl=True,
           tips=(f"Mesma configuração do WSJT-X: Hamlib NET rigctl em {RIGCTL_ADDRESS}.",)),
    ExtApp("js8call", "JS8Call", GROUPS[1], "Mensagens e conversas em JS8 (derivado do FT8), com retransmissão.",
           ("js8call.exe",), ("C:/JS8Call/bin/js8call.exe", "C:/Program Files*/JS8Call/bin/js8call.exe"),
           "https://js8call.com/", needs_rigctl=True,
           tips=(f"Settings > Radio: Hamlib NET rigctl em {RIGCTL_ADDRESS}, PTT = CAT; áudio: {SOUNDCARD}.",)),
    ExtApp("fldigi", "Fldigi", GROUPS[1], "PSK31, RTTY, Olivia, MT63, Contestia e muitos outros modos.",
           ("fldigi.exe",), ("C:/Program Files*/Fldigi*/fldigi.exe",), "http://www.w1hkj.com/", needs_rigctl=True,
           tips=(f"Rig Control > Hamlib: escolha NET rigctl e o endereço {RIGCTL_ADDRESS}.",)),
    ExtApp("freedv", "FreeDV", GROUPS[1], "Voz digital em HF, aberta e gratuita (codec de código aberto), com modos como 700D e 1600.",
           ("FreeDV.exe",), ("C:/Program Files*/FreeDV*/bin/FreeDV.exe", "C:/Program Files*/FreeDV*/FreeDV.exe"), "https://freedv.org/", needs_rigctl=True,
           tips=(f"Placa de som: {SOUNDCARD}. O PTT e a frequência podem vir do servidor rigctl em {RIGCTL_ADDRESS}.",)),
    ExtApp("mmsstv", "MMSSTV", GROUPS[1], "SSTV com muitos modos além de Martin e Scottie (que este app já faz).",
           ("MMSSTV.exe",), ("C:/MMSSTV/MMSSTV.exe", "C:/Program Files*/MMSSTV/MMSSTV.exe"), "https://hamsoft.ca/pages/mmsstv.php",
           tips=(f"Placa de som: {SOUNDCARD}. O PTT pode ser acionado por este app (servidor rigctl) ou pelo próprio MMSSTV.",)),
    ExtApp("n1mm", "N1MM Logger+", GROUPS[2], "Log de concursos com banco de dados, DX Cluster e controle do rádio.",
           ("N1MMLogger.net.exe",), ("C:/Program Files*/N1MM Logger+/N1MMLogger.net.exe",), "https://n1mmwp.hamdocs.com/",
           tips=("O N1MM controla o IC-7300 pela porta COM. Se este app estiver conectado à mesma porta, desconecte antes.",)),
)


def by_key(key: str) -> ExtApp:
    return next(a for a in APPS if a.key == key)


def find(app: ExtApp, custom: str = "") -> Optional[Path]:
    """Caminho do executável: o escolhido pelo usuário, os locais comuns de instalação ou o PATH."""
    if custom and Path(custom).is_file():
        return Path(custom)
    for pattern in app.globs:
        for hit in sorted(glob.glob(os.path.expandvars(pattern))):
            if Path(hit).is_file():
                return Path(hit)
    for exe in app.exe:
        found = shutil.which(exe)
        if found:
            return Path(found)
    return None


def launch(path: Path) -> int:
    """Abre o programa separado deste app (ele continua aberto se o app fechar). Retorna o PID."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([str(path)], cwd=str(path.parent), close_fds=True, creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.pid

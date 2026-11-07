"""Programas de terceiros: como instalar (winget ou página oficial) e instruções de configuração com os dados do operador.

Nada é redistribuído por este app. Os instaladores vêm sempre do site oficial de cada programa: o winget (repositório da
Microsoft) baixa de lá e confere o hash do instalador; o que não está no winget abre a página oficial.
"""
from __future__ import annotations

import html
import shutil
from dataclasses import dataclass

from . import extapps

# programas com pacote no winget (conferidos em 07/11/2026): código do app -> id do pacote
WINGET_IDS = {
    "wsjtx": "JoeTaylor.WSJT-X",
    "js8call": "KN4CRD.JS8Call",
    "fldigi": "w1hkj.fldigi",
    "winlink_express": "Winlink.WinlinkExpress",
    "freedv": "FreeDV.FreeDV",
}
# apps oferecidos pelo assistente, na ordem de exibição
OFFERED = ("wsjtx", "js8call", "fldigi", "winlink_express", "pat", "vara_hf", "varac", "freedv", "mmsstv", "n1mm")
LICENSE_NOTES = {
    "vara_hf": "Proprietário (EA5HVK): gratuito com velocidade limitada; a versão completa exige registro pago do autor.",
    "varac": "Proprietário, gratuito para uso pessoal; precisa do VARA HF instalado.",
    "winlink_express": "Proprietário e gratuito; exige conta no Winlink (cadastro gratuito do seu indicativo).",
    "js8call": "Licença própria do autor (o pacote do winget a marca como proprietária).",
    "n1mm": "Gratuito; baixe do site oficial (exige aceitar a licença).",
    "mmsstv": "Gratuito; baixe do site oficial.",
}


@dataclass
class OperatorInfo:
    callsign: str = ""
    name: str = ""
    city: str = ""
    grid: str = ""
    lat: float = 0.0
    lon: float = 0.0
    port: str = ""
    audio_in: str = "USB Audio CODEC"
    audio_out: str = "USB Audio CODEC"
    rigctl_port: int = 4532

    @property
    def rigctl(self) -> str:
        return f"127.0.0.1:{self.rigctl_port}"


def winget_path() -> str | None:
    return shutil.which("winget")


def winget_args(app_key: str) -> list[str]:
    """Argumentos do `winget install` (silencioso, pacote exato, aceitando os termos do repositório)."""
    return ["install", "--id", WINGET_IDS[app_key], "--exact", "--silent", "--accept-package-agreements",
            "--accept-source-agreements"]


def method(app_key: str) -> str:
    return "winget" if app_key in WINGET_IDS else "página oficial"


# ---------------------------------------------------------------------------------------------- instruções
_RADIO = ("<b>No IC-7300</b> (menu SET > Connectors): CI-V Address = 94h; CI-V USB Baud Rate = 115200; "
          "CI-V USB Port = Unlink from [REMOTE]; USB SEND = em RTS/DTR somente se o programa pedir PTT por RTS/DTR. "
          "Em DATA MOD, escolha USB. Só um programa deve comandar a porta COM por vez.")


def _rig_net(i: OperatorInfo) -> str:
    return f"Rig = <b>Hamlib NET rigctl</b>, servidor <b>{i.rigctl}</b> (ligue o servidor rigctl nas Configurações deste app)"


def _steps(*items: str) -> str:
    return "<ol>" + "".join(f"<li>{t}</li>" for t in items) + "</ol>"


def instructions_html(app_key: str, i: OperatorInfo) -> str:
    app = extapps.by_key(app_key)
    call, grid = html.escape(i.callsign or "SEU-INDICATIVO"), html.escape(i.grid or "SEU-GRID")
    snd_in, snd_out = html.escape(i.audio_in), html.escape(i.audio_out)
    port = html.escape(i.port or "a porta COM do IC-7300 (Silicon Labs CP210x)")
    body: str
    if app_key in ("wsjtx", "js8call"):
        body = _steps(
            f"Abra o programa e vá em <b>File > Settings > General</b>: My Call = <b>{call}</b>, My Grid = <b>{grid}</b>.",
            f"Aba <b>Radio</b>: {_rig_net(i)}; PTT Method = <b>CAT</b>; Mode = <b>Data/Pkt</b>; Split Operation = Fake It (se usar mais de 3 kHz).",
            f"Aba <b>Audio</b>: Input e Output = <b>{snd_in}</b> / <b>{snd_out}</b> (Output: sem Windows sounds).",
            "Teste o PTT com <b>Tune</b> numa carga fantasma ou em potência baixa; o ALC não deve acionar.",
            "Não transmita ao mesmo tempo que o FT8 deste app.") + f"<p>{_RADIO}</p>"
    elif app_key == "fldigi":
        body = _steps(
            f"<b>Configure > Operator</b>: Callsign = <b>{call}</b>, Name = <b>{html.escape(i.name)}</b>, QTH = <b>{html.escape(i.city)}</b>, Locator = <b>{grid}</b>.",
            f"<b>Configure > Rig Control > Hamlib</b>: Use Hamlib, Rig = NET rigctl, Device = <b>{i.rigctl}</b>, PTT via Hamlib command.",
            f"<b>Configure > Sound Card > Devices</b>: PortAudio, Capture e Playback = <b>{snd_in}</b>.") + f"<p>{_RADIO}</p>"
    elif app_key == "winlink_express":
        body = _steps(
            "Cadastre o indicativo em winlink.org (gratuito) para ter a conta e a senha; a senha é só sua e vai direto no programa.",
            f"Na primeira execução: Callsign = <b>{call}</b>, grid square = <b>{grid}</b>, senha do Winlink, e-mail de recuperação.",
            f"<b>Settings > Radio Setup</b>: modelo do rádio ICOM IC-7300, porta serial <b>{port}</b>, 115200 baud, endereço CI-V 94h "
            "(se a sua versão não listar o modelo, use o servidor rigctl se houver opção Hamlib).",
            f"Escolha o modo (VARA HF, Packet...) e a placa de som <b>{snd_in}</b> no próprio modem.",
            "Para o rádio ser dividido com este app, desconecte este app da porta COM antes de abrir o Winlink Express.")
    elif app_key == "pat":
        body = _steps(
            "Instale o Pat pelo site oficial e rode <code>pat configure</code> (abre o arquivo de configuração).",
            f"Preencha <code>mycall</code> = <b>{call}</b> e <code>locator</code> = <b>{grid}</b>.",
            f"Para controlar o rádio pelo servidor rigctl deste app, cadastre um rig Hamlib com endereço <b>{i.rigctl}</b> "
            "(veja o exemplo na documentação do Pat em getpat.io) e vincule-o ao modem VARA ou ARDOP.",
            f"Placa de som do modem: <b>{snd_in}</b>. A interface do Pat abre no navegador (porta 8080).")
    elif app_key == "vara_hf":
        body = _steps(
            "Instale o VARA HF e abra uma vez. Não há rádio nem indicativo para preencher aqui: quem aciona o modem é o Winlink Express, o Pat ou o VarAC.",
            f"<b>Settings > SoundCard</b>: Input e Output = <b>{snd_in}</b> / <b>{snd_out}</b>; ajuste o nível para o ALC do rádio não acionar.",
            "O modem usa as portas TCP 8300 (comandos) e 8301 (dados) em 127.0.0.1.",
            "Registro: a versão gratuita é lenta; para a completa, compre a chave do autor (EA5HVK) e informe em <b>Settings > Register</b>.")
    elif app_key == "varac":
        body = _steps(
            "Instale o VARA HF antes e deixe-o aberto.",
            f"Na primeira execução do VarAC: Callsign = <b>{call}</b>, Grid = <b>{grid}</b>.",
            f"Controle do rádio: porta COM <b>{port}</b> (115200) com endereço CI-V 94h <i>ou</i> Hamlib em <b>{i.rigctl}</b>. Use só um dos dois.",
            "Caminho do VARA: informe o VARA.exe instalado (geralmente em C:\\VARA).")
    elif app_key == "freedv":
        body = _steps(f"<b>Tools > Options</b>: Callsign = <b>{call}</b>, grid = <b>{grid}</b>.",
                      f"Áudio: entrada e saída <b>{snd_in}</b>; PTT por Hamlib em <b>{i.rigctl}</b>.")
    elif app_key == "mmsstv":
        body = _steps(f"Placa de som: <b>{snd_in}</b> / <b>{snd_out}</b>.",
                      "PTT: deixe a cargo deste app (servidor rigctl) ou configure a porta COM do rádio no próprio MMSSTV.",
                      f"Seu indicativo <b>{call}</b> entra em <b>Option > Setup MMSSTV > Misc</b> (texto das imagens).")
    elif app_key == "n1mm":
        body = _steps(f"<b>Config > Change Your Station Data</b>: Callsign = <b>{call}</b>, Name = {html.escape(i.name)}, Grid = <b>{grid}</b>.",
                      f"<b>Config > Configure Ports</b>: porta <b>{port}</b>, 115200 baud; rádio Icom IC-7300 (endereço 94h).",
                      "O N1MM comanda o rádio pela porta COM: se este app estiver conectado à mesma porta, desconecte um deles.")
    else:
        body = _steps(*app.tips) if app.tips else "<p>Sem passos específicos.</p>"
    note = LICENSE_NOTES.get(app_key, "")
    return (f"<h3>{html.escape(app.name)}</h3><p>{html.escape(app.summary)}</p>{body}"
            + (f"<p><i>Licença: {html.escape(note)}</i></p>" if note else "")
            + f"<p>Site oficial: <a href='{app.url}'>{app.url}</a></p>")


def all_instructions_html(keys: list[str] | tuple[str, ...], i: OperatorInfo) -> str:
    head = ("<html><head><meta charset='utf-8'><title>Configuração dos programas</title></head><body style='font-family:Segoe UI,sans-serif'>"
            f"<h2>Configuração dos programas de terceiros</h2><p>Operador: <b>{html.escape(i.callsign)}</b> "
            f"{html.escape(i.name)} · {html.escape(i.city)} · grid {html.escape(i.grid)}</p>"
            "<p>Passos baseados nos menus usuais de cada programa; as versões mudam e a documentação do autor vale mais.</p>")
    return head + "<hr>".join(instructions_html(k, i) for k in keys) + "</body></html>"

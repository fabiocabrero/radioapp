"""Gera data/protocols.json: catálogo de protocolos/modos e centros de atividade.

Fontes: IARU Region 2 Band Plan (set/2020: categorias CW, DM, DV, ACDS, imagem, IBP e centros de atividade), ARRL Band Plan
(sub-bandas de RTTY/dados e pacote) e 47 CFR § 97.309 (códigos digitais especificados). Larguras de banda são valores típicos.
Uso: python tools/build_protocols.py <pasta do projeto>
"""
import json
import sys

FCC_SPEC = "Código especificado na FCC § 97.309(a)"
FCC_DOC = "Técnica documentada publicamente, citada na FCC § 97.309(a)(4)"
FCC_OTHER = ("Para códigos não especificados vale a regra de documentação pública (FCC § 97.309): consulte a regulamentação do seu país "
             "para modos cuja modulação não é publicada")

PROTOCOLS = [
    dict(key="cw", name="CW (telegrafia)", category="Telegrafia", iaru="CW", bw="100 a 500 Hz", app="native", page="cw",
         summary="Código Morse; permitido em toda a banda, de preferência fora de segmentos de balizas e repetidoras (IARU).",
         recognition="IARU: CW em todas as faixas. FCC § 97.305(a): CW em qualquer frequência autorizada."),
    dict(key="rtty", name="RTTY (Baudot)", category="Texto", iaru="DM", bw="≈ 250 Hz", app="native", page="rtty",
         summary="Teletipo em AFSK: 45,45 baud, 170 Hz de shift, código Baudot (ITA2).",
         where="ARRL: 'RTTY/Data' em 80 m 3,570-3,600 e 40 m 7,080-7,125; RTTY em 30 m 10,130-10,140, 20 m 14,070-14,095, 17 m 18,100-18,105, 15 m 21,070-21,110, 12 m 24,920-24,925 e 10 m 28,070-28,150 MHz.",
         recognition=f"IARU: modo digital (DM). {FCC_SPEC}(1): Baudot."),
    dict(key="psk31", name="PSK31 e família PSK", category="Texto", iaru="DM", bw="≈ 31 Hz (PSK31)", app="external", ext="fldigi",
         summary="Teclado a teclado em fase (BPSK/QPSK), muito estreito. Use o Fldigi.",
         where="Dentro dos segmentos de modos digitais (DM); 14,070 MHz é a frequência tradicional de PSK31.",
         recognition=f"IARU: modo digital (DM). {FCC_OTHER}."),
    dict(key="olivia", name="Olivia, MT63, Contestia, THOR", category="Texto", iaru="DM", bw="250 Hz a 2 kHz", app="external", ext="fldigi",
         summary="Modos robustos com correção de erros para texto com sinais muito fracos. Disponíveis no Fldigi.",
         recognition=f"IARU: modo digital (DM). {FCC_OTHER}."),
    dict(key="ft8", name="FT8", category="Sinais fracos", iaru="DM", bw="50 Hz", app="native", page="ft8",
         summary="Ciclos de 15 s, mensagens fixas de 77 bits; o modo digital mais ativo em HF.",
         where="Frequências de chamada na tabela de Frequências digitais (por exemplo 14,074 MHz).",
         recognition=f"IARU: modo digital (DM). {FCC_OTHER}. A IARU revisou os planos de HF por causa do volume de FT8."),
    dict(key="ft4", name="FT4", category="Sinais fracos", iaru="DM", bw="83 Hz", app="native", page="ft8",
         summary="Como o FT8, em ciclos de 7,5 s, para concursos.", recognition=f"IARU: modo digital (DM). {FCC_OTHER}."),
    dict(key="wsjt", name="FST4, Q65, JT65, JT9", category="Sinais fracos", iaru="DM", bw="10 a 200 Hz", app="engine", page="wsjt",
         summary="Modos do WSJT-X para sinais muito fracos (inclusive EME e dispersão). Recepção pelo motor do WSJT-X instalado.",
         recognition=f"IARU: modo digital (DM). {FCC_OTHER}."),
    dict(key="wspr", name="WSPR", category="Balizas", iaru="DM / ACDS", bw="6 Hz", app="engine", page="wsjt",
         summary="Balizas de 2 minutos para medir propagação; recepção pelo motor do WSJT-X.",
         recognition="IARU: balizas digitais podem ser ACDS onde o segmento indicar; use banda estreita."),
    dict(key="js8", name="JS8 (JS8Call)", category="Texto", iaru="DM", bw="≈ 50 Hz", app="external", ext="js8call",
         summary="Mensagens e conversas sobre a base do FT8, com retransmissão por estações intermediárias.",
         recognition=f"IARU: modo digital (DM). {FCC_OTHER}."),
    dict(key="winlink", name="Winlink (e-mail por rádio)", category="E-mail por rádio", iaru="DM / ACDS", bw="500 Hz a 2,75 kHz", app="external", ext="winlink_express",
         summary="Rede de e-mail por rádio. Os modems são ARDOP (aberto), VARA (proprietário), PACTOR (proprietário, com hardware) e Packet. "
                 "Gateways automáticos operam nos segmentos ACDS.",
         where="Segmentos ACDS do plano IARU R2: 80 m 3,590-3,600; 40 m 7,047-7,053; 30 m 10,130-10,140; 20 m 14,089-14,112; 17 m 18,105-18,120; 15 m 21,090-21,120; 12 m 24,925-24,940; 10 m 28,120-28,150 MHz.",
         recognition=f"IARU: ACDS só onde o segmento indica; operação sem operador é restrita em HF. {FCC_DOC} (CLOVER, G-TOR, PACTOR)."),
    dict(key="ardop", name="ARDOP", category="E-mail por rádio", iaru="DM / ACDS", bw="200 a 2000 Hz", app="external", ext="ardopcf",
         summary="Modem ARQ aberto, usado pelo Pat e pelo Winlink Express. Alternativa livre ao VARA.",
         recognition=f"IARU: DM/ACDS. {FCC_OTHER}."),
    dict(key="vara", name="VARA HF", category="E-mail por rádio", iaru="DM / ACDS", bw="500 Hz a 2,75 kHz", app="external", ext="vara_hf",
         summary="Modem proprietário (EA5HVK) de alta velocidade; só existe como programa próprio, não dá para embutir.",
         recognition=f"IARU: DM/ACDS. {FCC_OTHER}."),
    dict(key="varac", name="VarAC", category="E-mail por rádio", iaru="DM", bw="a do VARA HF", app="external", ext="varac",
         summary="Chat e mensagens curtas sobre o VARA HF.", recognition=f"Depende do VARA. {FCC_OTHER}."),
    dict(key="pactor", name="PACTOR", category="E-mail por rádio", iaru="DM / ACDS", bw="500 Hz a 2,4 kHz", app="none",
         summary="Modem com hardware proprietário, citado na regra da FCC; usado em Winlink e marítimo. Sem suporte neste app.",
         recognition=f"{FCC_DOC}."),
    dict(key="packet", name="Packet (AX.25)", category="Pacote", iaru="DM", bw="≈ 500 Hz (300 baud HF)", app="none",
         summary="Pacotes AX.25 a 300 baud em HF e 1200 baud em VHF. Sem suporte neste app (use o Pat/Dire Wolf).",
         where="ARRL: packet em 30 m 10,140-10,150, 20 m 14,095-14,0995 e 14,1005-14,112, 17 m 18,105-18,110 e 12 m 24,925-24,930 MHz; 6 m 50,62 (chamada).",
         recognition=f"IARU: DM. {FCC_SPEC}(3): ASCII."),
    dict(key="sstv", name="SSTV e imagem", category="Imagem", iaru="Imagem", bw="≈ 2,7 kHz", app="native", page="sstv",
         summary="Televisão de varredura lenta (Martin, Scottie e outros) e fax; IARU define centros de atividade de imagem.",
         where="Centros de atividade de imagem (IARU R2): 3,735; 3,845; 7,165; 14,230; 21,340 e 28,680 MHz.",
         recognition="IARU: modos de imagem (SSTV e FAX) em qualquer segmento que admita a largura de banda."),
    dict(key="dv", name="Voz digital (FreeDV)", category="Voz digital", iaru="DV", bw="≈ 1 kHz", app="external", ext="freedv",
         summary="Voz codificada digitalmente em HF; os dados embutidos devem ser acessórios. O FreeDV é aberto.",
         where="Centros de voz digital (IARU R2): 7,070 e 28,330 MHz.",
         recognition="IARU: DV deve verificar se o canal está em uso, inclusive por modos analógicos."),
    dict(key="ibp", name="Balizas internacionais (IBP)", category="Balizas", iaru="IBP", bw="CW", app="none",
         summary="Rede mundial de balizas da IARU, uma frequência por banda, em segmentos exclusivos; sem transmitir nelas.",
         where="14,100; 18,110; 21,150; 24,930 e 28,200 MHz (segmentos de 2 kHz exclusivos).",
         recognition="IARU: IBP exclusivo; use só para receber."),
]

CENTERS = (
    [("Emergência", f"{k:g} kHz", k) for k in (3750, 3985, 7060, 7240, 7275, 14300, 18160, 21360)] +
    [("Imagem (SSTV/FAX)", f"{k:g} kHz", k) for k in (3735, 3845, 7165, 14230, 21340, 28680)] +
    [("Voz digital", f"{k:g} kHz", k) for k in (7070, 28330)] +
    [("CW QRP", f"{k:g} kHz", k) for k in (1812, 3560, 7030, 10116, 14060, 18086, 21060, 24906, 28060)] +
    [("CW QRS", f"{k:g} kHz", k) for k in (3555, 14055, 28055)] +
    [("SSB QRP", f"{k:g} kHz", k) for k in (1910, 3690, 7090, 7285, 14285, 18130, 21285, 24950, 28360)] +
    [("AM", f"{k:g} kHz", k) for k in (3885, 7290, 14285)] +
    [("FM chamada", "29600 kHz", 29600)] + [("6 m", "chamada DX 50110 kHz (exclusiva)", 50110), ("6 m", "centro PSK 50305 kHz", 50305)]
)

if __name__ == "__main__":
    repo = sys.argv[1]
    out = {"_fonte": ("IARU Region 2 Band Plan (2020); ARRL Band Plan; 47 CFR 97.309. Larguras de banda são valores típicos. "
                      "Centros de atividade são voluntários."),
           "protocols": PROTOCOLS, "centers": [{"kind": k, "label": l, "khz": f} for k, l, f in CENTERS]}
    json.dump(out, open(f"{repo}/ic7300/data/protocols.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(len(PROTOCOLS), "protocolos,", len(CENTERS), "centros de atividade")

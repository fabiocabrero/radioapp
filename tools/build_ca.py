"""Gerador do plano do Canadá (Tabela I do RBR-4, Issue 3). Rode depois que o plano IARU-R2 existir. Uso: python tools/build_ca.py <pasta do projeto>"""
import copy
import json
import sys

repo = sys.argv[1]
path = f"{repo}/ic7300/data/bandplans.json"
data = json.load(open(path, encoding="utf-8"))
r2 = {b["name"]: b for b in data["plans"]["IARU-R2"]["bands"]}

# Tabela I do RBR-4 (Issue 3, jul/2022), em kHz: (banda, início, fim, largura máx., classes que podem usar, modos, nota)
HF = "HA"      # Básico com Honours (B/H, ou Básico + Morse 5 wpm) e Avançado
ALL = "BHA"    # Básico, Básico com Honours e Avançado
TABLE = [
    ("160m", 1800, 2000, "6 kHz", HF, [], ""),
    ("80m", 3500, 4000, "6 kHz", HF, [], ""),
    ("40m", 7000, 7300, "6 kHz", HF, [], "Aceitar interferência de radiodifusão (5.142)"),
    ("30m", 10100, 10150, "1 kHz", HF, ["CW", "DIG"], "Largura máxima de 1 kHz: só CW e modos digitais estreitos"),
    ("20m", 14000, 14350, "6 kHz", HF, [], ""),
    ("17m", 18068, 18168, "6 kHz", HF, [], ""),
    ("15m", 21000, 21450, "6 kHz", HF, [], ""),
    ("12m", 24890, 24990, "6 kHz", HF, [], ""),
    ("10m", 28000, 29700, "20 kHz", HF, [], ""),
    ("6m", 50000, 54000, "30 kHz", ALL, [], ""),
]
bands = []
for name, lo, hi, bw, classes, modes, note in TABLE:
    segs = []
    for s in copy.deepcopy(r2[name]["segments"]):
        a, z = max(s["start"], lo * 1000), min(s["stop"], hi * 1000)
        if z > a:
            segs.append({"start": a, "stop": z, "use": s["use"], "modes": list(modes), "classes": classes,
                         "note": f"Largura máx. {bw}" + (f". {note}" if note else "")})
    segs[0]["start"], segs[-1]["stop"] = lo * 1000, hi * 1000
    bands.append({"name": name, "start": lo * 1000, "stop": hi * 1000, "segments": segs})
# 60 m: cinco canais de 2,8 kHz (5.332, 5.348, 5.3515-5.3665, 5.373 e 5.405 MHz)
chan = []
for c0, c1, note in [(5330.6, 5333.4, "5332 kHz"), (5346.6, 5349.4, "5348 kHz"), (5351.5, 5366.5, "5351,5-5366,5 kHz"),
                     (5371.6, 5374.4, "5373 kHz"), (5403.6, 5406.4, "5405 kHz")]:
    chan.append({"start": int(round(c0 * 1000)), "stop": int(round(c1 * 1000)), "use": "SSB", "modes": ["CW", "DIG", "SSB"],
                 "classes": HF, "note": f"Largura máx. 2,8 kHz ({note}); sem interferir nem ser protegido de outros serviços (C21)"})
bands.insert(2, {"name": "60m", "start": chan[0]["start"], "stop": chan[-1]["stop"], "segments": chan})

plan = {"name": "Canadá (ISED, RBR-4)", "region": 2, "generic": False,
        "classes": {"B": "Básico (sem HF)", "H": "Básico com Honours ou Morse 5 wpm", "A": "Avançado"},
        "source": "ISED RBR-4, Issue 3 (jul/2022), Tabela I: faixas, larguras de banda e qualificações exigidas; potências nos itens 10.2 e 10.3. "
                  "O uso dos segmentos (CW/digital/fonia) segue o plano IARU Região 2 (típico, não é exigência legal). Texto lido de uma cópia do documento.",
        "max_power": {"B": 560, "H": 560, "A": 2250},
        "power_note": "Valores em PEP de SSB. Básico (com ou sem Honours): 250 W de entrada CC ou 560 W PEP SSB ou 190 W de portadora (outras emissões). "
                      "Avançado: 1000 W CC ou 2250 W PEP SSB ou 750 W de portadora.",
        "bands": bands}
data["plans"]["CA"] = plan
json.dump(data, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
for b in bands:
    print(b["name"], [(s["start"] / 1000, s["stop"] / 1000, s["use"], s["classes"], s["modes"]) for s in b["segments"]][:3], "...")

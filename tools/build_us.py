"""Gerador do plano dos EUA (valores de 47 CFR Parte 97 no eCFR). Uso: python tools/build_us.py <pasta do projeto>"""
import sys

from plan_builder import PHONE, add_plan, build_band

repo = sys.argv[1]
ALL = ["E", "A", "G", "T"]
DATA = ["CW", "DIG"]
PH = ["CW"] + PHONE + ["OUT"]          # fonia e imagem (SSTV); CW é permitido em qualquer frequência
T_CW = {"T": ["CW"]}


def full(lo, hi, classes=("E", "A", "G")):
    return {c: [(lo, hi)] for c in classes}


bands = []
# 160 m: Extra, Advanced, General (Technician não tem)
bands.append(build_band("160m", full(1800, 2000), [(1800, 2000, DATA + PHONE + ["OUT"])]))
# 80 m / 75 m
bands.append(build_band("80m", {"E": [(3500, 3600), (3600, 4000)], "A": [(3525, 3600), (3700, 4000)], "G": [(3525, 3600), (3800, 4000)],
                                "T": [(3525, 3600)]},
                        [(3500, 3600, DATA), (3600, 4000, PH)], class_modes={(3525, 3600, "T"): ["CW"]}))
# 60 m: quatro canais discretos (portadora 1,5 kHz abaixo do centro) e 5351,5-5366,5 kHz
sixty = {c: [(5330.5, 5333.5), (5346.5, 5349.5), (5351.5, 5366.5), (5371.5, 5374.5), (5403.5, 5406.5)] for c in ("E", "A", "G")}
bands.append(build_band("60m", sixty, [(5330.5, 5406.5, ["CW", "DIG", "SSB"])],
                        notes=[(5330.5, 5333.5, "Canal 5332 kHz: até 100 W ERP"), (5346.5, 5349.5, "Canal 5348 kHz: até 100 W ERP"),
                               (5351.5, 5366.5, "Até 9,15 W ERP (97.313)"), (5371.5, 5374.5, "Canal 5373 kHz: até 100 W ERP"),
                               (5403.5, 5406.5, "Canal 5405 kHz: até 100 W ERP")]))
# 40 m: Technician e Novice só CW; fonia em 7075-7100 apenas no oeste de 130°W ou ao sul de 20°N
bands.append(build_band("40m", {"E": [(7000, 7300)], "A": [(7025, 7300)], "G": [(7025, 7125), (7175, 7300)], "T": [(7025, 7125)]},
                        [(7000, 7125, DATA), (7125, 7300, PH)], class_modes={(7025, 7125, "T"): ["CW"]},
                        notes=[(7075, 7100, "Fonia só a oeste de 130°W ou ao sul de 20°N (97.307(f)(11))"),
                               (7200, 7300, "Aceitar interferência de radiodifusão internacional (97.303(i))")]))
bands.append(build_band("30m", full(10100, 10150), [(10100, 10150, DATA)], notes=[(10100, 10150, "Potência máxima 200 W PEP (97.313(c))")]))
bands.append(build_band("20m", {"E": [(14000, 14350)], "A": [(14025, 14150), (14175, 14350)], "G": [(14025, 14150), (14225, 14350)]},
                        [(14000, 14150, DATA), (14150, 14350, PH)]))
bands.append(build_band("17m", full(18068, 18168), [(18068, 18110, DATA), (18110, 18168, PH)]))
bands.append(build_band("15m", {"E": [(21000, 21450)], "A": [(21025, 21200), (21225, 21450)], "G": [(21025, 21200), (21275, 21450)],
                                "T": [(21025, 21200)]},
                        [(21000, 21200, DATA), (21200, 21450, PH)], class_modes={(21025, 21200, "T"): ["CW"]}))
bands.append(build_band("12m", full(24890, 24990), [(24890, 24930, DATA), (24930, 24990, PH)]))
bands.append(build_band("10m", {"E": [(28000, 29700)], "A": [(28000, 29700)], "G": [(28000, 29700)], "T": [(28000, 28500)]},
                        [(28000, 28300, DATA), (28300, 29700, PH)], class_modes={(28300, 28500, "T"): ["CW", "SSB"]}))
bands.append(build_band("6m", {c: [(50000, 54000)] for c in ALL}, [(50000, 50100, ["CW"]), (50100, 54000, ["CW", "DIG"] + PHONE + ["OUT"])]))

plan = {"name": "Estados Unidos (FCC, 47 CFR Parte 97)", "region": 2, "generic": False,
        "classes": {"E": "Amateur Extra", "A": "Advanced", "G": "General", "T": "Technician / Novice"},
        "source": "47 CFR §§ 97.301, 97.303, 97.305, 97.307 e 97.313 (eCFR, texto de 29/10/2026), coluna da Região 2, estação nos EUA contíguos. "
                  "O Advanced não emite mais licenças, mas continua com seus privilégios.",
        "max_power": {"E": 1500, "A": 1500, "G": 1500, "T": 200},
        "power_note": "Máximo de 1,5 kW PEP (200 W PEP em 30 m e, para Technician, nos trechos de 80/40/15/10 m). 60 m: 100 W ERP nos canais e 9,15 W ERP em 5351,5-5366,5 kHz.",
        "bands": bands}
add_plan(f"{repo}/ic7300/data/bandplans.json", "US", plan)
for b in bands:
    print(b["name"])
    for s in b["segments"]:
        cm = f" {s['class_modes']}" if "class_modes" in s else ""
        print(f"   {s['start'] / 1000:>9g}-{s['stop'] / 1000:<9g} {s['use']:<4} {s['classes']:<4} {','.join(s['modes'])}{cm} {s.get('note', '')}")

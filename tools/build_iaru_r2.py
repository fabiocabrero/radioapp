"""Gera o plano 'IARU-R2' a partir da transcrição do IARU Region 2 Band Plan (set/2020), HF e 6 m.

Fonte: https://www.iaru.org/wp-content/uploads/2020/10/IARU-Region-2-Band-plan.pdf
Valores em kHz. Modos: CW, DM (modos digitais), SSB, All (todos os modos), FM, REP (repetidoras), IBP (balizas exclusivas).
(*) = AM de até 6 kHz permitida. O PDF tem um erro de digitação em 17 m (18095-15105); aqui vale 18095-18105.
Uso: python tools/build_iaru_r2.py <pasta do projeto>
"""
import json
import sys

# (início, fim, largura Hz, modos, nota, AM)
T = {
    "160m": [(1800, 1810, 500, "DM", "", 0), (1810, 1830, 200, "CW", "CW QRP, centro 1812", 0), (1830, 1839, 200, "CW", "Janela de DX", 0),
             (1839, 1840, 200, "CW,DM", "Janela de DX; ACDS", 0), (1840, 1843, 2700, "CW,SSB,DM", "Janela de DX; digital só até 200 Hz de largura", 0),
             (1843, 1850, 2700, "CW,SSB", "Janela de DX", 0), (1850, 2000, 2700, "All", "Centro QRP SSB 1910", 1)],
    "80m": [(3500, 3510, 200, "CW", "Janela de DX", 0), (3510, 3560, 200, "CW", "CW QRS, centro 3555; preferência de concurso CW", 0),
            (3560, 3570, 200, "CW", "CW QRP, centro 3560", 0), (3570, 3580, 200, "CW,DM", "", 0), (3580, 3590, 500, "CW,DM", "", 0),
            (3590, 3600, 500, "CW,DM", "ACDS", 0), (3600, 3625, 2700, "All", "ACDS", 1), (3625, 3650, 2700, "All", "Preferência de concurso SSB", 0),
            (3650, 3700, 2700, "All", "Centro QRP 3690", 0),
            (3700, 3775, 2700, "All", "Concurso SSB; centro de imagem 3735; centro de emergência 3750", 0), (3775, 3800, 2700, "All", "Janela de DX", 0),
            (3800, 3875, 2700, "All", "", 0), (3875, 3900, 2700, "All", "Centro de imagem 3845; centro AM 3885", 1),
            (3900, 4000, 2700, "All", "Centro de emergência 3985", 0)],
    "60m": [(5351.5, 5354, 500, "CW,DM", "", 0), (5354, 5366, 2700, "All", "", 0), (5366, 5366.5, 20, "CW,DM", "ACDS", 0)],
    "40m": [(7000, 7025, 200, "CW", "Janela de DX", 0), (7025, 7040, 200, "CW", "CW QRP, centro 7030", 0), (7040, 7047, 500, "CW,DM", "", 0),
            (7047, 7050, 500, "CW,DM", "ACDS", 0), (7050, 7053, 2700, "All", "ACDS", 0), (7053, 7060, 2700, "All", "Centro de emergência R2 7060", 0),
            (7060, 7100, 2700, "All", "Centro de voz digital 7070; SSB QRP 7090; concurso SSB", 0), (7100, 7130, 2700, "All", "", 1),
            (7130, 7200, 2700, "All", "Concurso SSB; centro de imagem 7165", 1),
            (7200, 7300, 2700, "All", "Emergência 7240 e 7275; SSB QRP 7285; centro AM 7290", 1)],
    "30m": [(10100, 10130, 200, "CW", "CW QRP, centro 10116", 0), (10130, 10140, 500, "CW,DM", "ACDS", 0), (10140, 10150, 2700, "CW,DM", "", 0)],
    "20m": [(14000, 14025, 200, "CW", "Janela de DX", 0), (14025, 14060, 200, "CW", "Concurso CW; CW QRS, centro 14055", 0),
            (14060, 14070, 200, "CW", "CW QRP, centro 14060", 0), (14070, 14089, 500, "CW,DM", "", 0), (14089, 14099, 500, "CW,DM", "ACDS", 0),
            (14099, 14101, 200, "IBP", "IBP: balizas internacionais (exclusivo)", 0), (14101, 14112, 2700, "All", "ACDS", 0),
            (14112, 14190, 2700, "All", "Concurso SSB", 0), (14190, 14200, 2700, "All", "Janela de DX; concurso SSB", 0),
            (14200, 14285, 2700, "All", "Concurso SSB; centro de imagem 14230; SSB QRP 14285", 0),
            (14285, 14300, 2700, "All", "Chamada AM 14285", 1), (14300, 14350, 2700, "All", "Centro de emergência global 14300", 0)],
    "17m": [(18068, 18095, 200, "CW", "CW QRP, centro 18086", 0), (18095, 18105, 500, "CW,DM", "", 0), (18105, 18109, 500, "CW,DM", "ACDS", 0),
            (18109, 18111, 200, "IBP", "IBP: balizas internacionais (exclusivo)", 0), (18111, 18120, 2700, "All", "ACDS", 0),
            (18120, 18168, 2700, "All", "QRP 18130; centro de emergência global 18160", 0)],
    "15m": [(21000, 21070, 200, "CW", "CW QRP, centro 21060", 0), (21070, 21090, 500, "CW,DM", "", 0), (21090, 21110, 500, "CW,DM", "ACDS", 0),
            (21110, 21120, 2700, "CW,DM", "ACDS", 0), (21120, 21149, 500, "All", "", 0),
            (21149, 21151, 200, "IBP", "IBP: balizas internacionais (exclusivo)", 0),
            (21151, 21380, 2700, "All", "SSB QRP 21285; imagem 21340; emergência global 21360", 0), (21380, 21450, 2700, "All", "", 1)],
    "12m": [(24890, 24915, 200, "CW", "CW QRP, centro 24906", 0), (24915, 24925, 500, "CW,DM", "", 0), (24925, 24929, 500, "CW,DM", "ACDS", 0),
            (24929, 24931, 200, "IBP", "IBP: balizas internacionais (exclusivo)", 0), (24931, 24940, 2700, "All", "ACDS", 0),
            (24940, 24990, 2700, "All", "SSB QRP 24950", 0)],
    "10m": [(28000, 28070, 200, "CW", "CW QRS 28055; CW QRP 28060", 0), (28070, 28120, 500, "CW,DM", "", 0), (28120, 28150, 500, "CW,DM", "ACDS", 0),
            (28150, 28190, 500, "CW,DM", "", 0), (28190, 28199, 200, "CW", "Balizas", 0),
            (28199, 28201, 200, "IBP", "IBP: balizas internacionais (exclusivo)", 0), (28201, 28225, 200, "CW", "Balizas", 0),
            (28225, 28300, 2700, "All", "Balizas", 0), (28300, 28320, 2700, "All", "ACDS", 0),
            (28320, 29000, 2700, "All", "Voz digital 28330; SSB QRP 28360; imagem 28680", 0), (29000, 29200, 6000, "All", "AM preferido", 0),
            (29200, 29300, 6000, "All", "ACDS", 0), (29300, 29510, 6000, "All", "Satélites", 0),
            (29520, 29590, 6000, "REP", "Entradas de repetidoras (exclusivo)", 0), (29590, 29620, 6000, "FM,DV", "Chamada FM 29600", 0),
            (29620, 29700, 6000, "REP", "Saídas de repetidoras (exclusivo)", 0)],
    "6m": [(50000, 50100, 500, "CW", "Balizas", 0), (50100, 50125, 2700, "CW,SSB", "Janela de DX; chamada 50110 (exclusiva)", 0),
           (50125, 50400, 2700, "CW,SSB,DM", "Centro PSK 50305", 0), (50400, 50500, 2700, "All", "Balizas, ACDS (balizas digitais)", 1),
           (50500, 50600, 2700, "All", "ACDS", 1), (50600, 50800, 12000, "All", "ACDS", 0), (50800, 51000, 12000, "All", "Controle remoto (canais de 20 kHz)", 0),
           (51000, 51110, 2700, "CW,SSB", "Janela de DX", 0), (51110, 51480, 12000, "REP", "Entradas de repetidoras (exclusivo)", 0),
           (51480, 51500, 12000, "FM,DV", "Não especificado no plano IARU (entre canais)", 0), (51500, 51600, 12000, "FM,DV", "Simplex", 0),
           (51600, 51620, 12000, "FM,DV", "Não especificado no plano IARU (entre canais)", 0), (51620, 51980, 12000, "REP", "Saídas de repetidoras (exclusivo)", 0),
           (51980, 52000, 12000, "FM,DV", "Não especificado no plano IARU (entre canais)", 0), (52000, 52100, 12000, "FM,DV", "IVG (voz sobre internet)", 0),
           (52100, 54000, 12000, "All", "", 0)],
}


def convert(lo, hi, bw, modes, note, am):
    if modes == "REP":
        m, use = ["REP"], "REP"
    elif modes == "IBP":
        m, use = ["BCN"], "BCN"
    else:
        parts = modes.split(",")
        m = []
        for p in parts:
            m += {"CW": ["CW"], "DM": ["DIG"], "SSB": ["SSB"], "FM": ["FM"], "DV": ["DV"],
                  "All": ["CW", "DIG", "SSB", "DV", "OUT"] + (["AM"] if am else []) + (["FM"] if bw >= 6000 else [])}[p]
        if "SSB" in m or "AM" in m:
            use = "ALL" if modes == "All" else "SSB"
        elif "FM" in m:
            use = "FM"
        elif "DIG" in m:
            use = "DIG"
        else:
            use = "CW"
    text = f"Largura máx. {bw} Hz" + (f". {note}" if note else "")
    if am and modes == "All":
        text += ". AM de até 6 kHz permitida"
    return {"start": round(lo * 1000), "stop": round(hi * 1000), "use": use, "modes": m, "classes": "", "note": text}


if __name__ == "__main__":
    repo = sys.argv[1]
    path = f"{repo}/ic7300/data/bandplans.json"
    data = json.load(open(path, encoding="utf-8"))
    bands = []
    for name, rows in T.items():
        segs = [convert(*r) for r in rows]
        for a, b in zip(segs, segs[1:]):
            assert a["stop"] == b["start"] or name in ("10m", "6m"), (name, a["stop"], b["start"])
        bands.append({"name": name, "start": segs[0]["start"], "stop": segs[-1]["stop"], "segments": segs})
    data["plans"]["IARU-R2"] = {
        "name": "IARU Região 2 (plano oficial, 2020)", "region": 2, "generic": True, "bands": bands,
        "source": "IARU Region 2 Band Plan (setembro de 2020), voluntário: confira o plano e as regras do seu país. "
                  "Siglas: DM = modos digitais, ACDS = estações de dados automáticas, IBP = balizas internacionais."}
    json.dump(data, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("segmentos:", sum(len(b["segments"]) for b in bands))

"""Constrói planos por país a partir de faixas por classe e de sub-bandas de emissão (valores em kHz)."""
import json

PHONE = ["SSB", "AM", "FM"]


def build_band(name, class_ranges, mode_ranges, class_modes=None, notes=None, beacons=None):
    """class_ranges: {classe: [(lo, hi), ...]}; mode_ranges: [(lo, hi, [modos])]; class_modes: {(lo, hi, classe): [modos]};
    notes: [(lo, hi, texto)]. Gera segmentos nos pontos de quebra de todas as listas."""
    points = set()
    for rs in class_ranges.values():
        for lo, hi in rs:
            points |= {lo, hi}
    for lo, hi, _ in mode_ranges:
        points |= {lo, hi}
    for lo, hi, _ in (notes or []):
        points |= {lo, hi}
    for (lo, hi, _c) in (class_modes or {}):
        points |= {lo, hi}
    lo_all = min(lo for rs in class_ranges.values() for lo, _ in rs)
    hi_all = max(hi for rs in class_ranges.values() for _, hi in rs)
    pts = sorted(p for p in points if lo_all <= p <= hi_all)
    segs = []
    for a, b in zip(pts, pts[1:]):
        mid = (a + b) / 2
        classes = "".join(sorted(c for c, rs in class_ranges.items() if any(lo <= mid < hi for lo, hi in rs)))
        modes = next((m for lo, hi, m in mode_ranges if lo <= mid < hi), None)
        if modes is None or not classes:
            continue  # sem emissão autorizada ou sem nenhuma classe: não é segmento transmissível
        seg = {"start": int(round(a * 1000)), "stop": int(round(b * 1000)), "modes": list(modes), "classes": classes}
        cm = {c: m for (lo, hi, c), m in (class_modes or {}).items() if lo <= mid < hi}
        if cm:
            seg["class_modes"] = cm
        note = " ".join(t for lo, hi, t in (notes or []) if lo <= mid < hi)
        if note:
            seg["note"] = note
        has_phone = any(m in modes for m in ("SSB", "AM", "FM"))
        seg["use"] = "SSB" if has_phone else ("DIG" if "DIG" in modes else "CW")
        segs.append(seg)
    # une vizinhos idênticos
    out = []
    for s in segs:
        if out and all(out[-1].get(k) == s.get(k) for k in ("use", "modes", "classes", "class_modes", "note")) and out[-1]["stop"] == s["start"]:
            out[-1]["stop"] = s["stop"]
        else:
            out.append(s)
    return {"name": name, "start": out[0]["start"], "stop": out[-1]["stop"], "segments": out}


def add_plan(path, plan_id, plan):
    data = json.load(open(path, encoding="utf-8"))
    data["plans"][plan_id] = plan
    json.dump(data, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

"""PDF report generation for Battery Sizer.

Creates a clean 4-page A4 report:
1. executive summary
2. charts
3. detailed analysis
4. simulated capacities table
"""

from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from fpdf import FPDF


SOLEOL_ORANGE = (233, 78, 53)
DARK = (25, 35, 48)
TEXT = (35, 35, 35)
MUTED = (100, 110, 120)
BLUE = (37, 99, 235)
GREEN = (34, 160, 85)
ORANGE = (245, 130, 32)
PURPLE = (126, 58, 242)
LIGHT_BG = (248, 250, 252)
LIGHT_ORANGE = (255, 244, 239)
LIGHT_GREEN = (236, 253, 245)
BORDER = (220, 225, 230)


def _tx(s) -> str:
    repl = {
        "—": "-",
        "–": "-",
        "→": "->",
        "≥": ">=",
        "≤": "<=",
        "≈": "~",
        "•": "-",
        "✅": "",
        "⚠️": "!",
        "’": "'",
        "œ": "oe",
        "…": "...",
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "ç": "c",
        "É": "E",
        "À": "A",
        "Ç": "C",
    }
    s = str(s)
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _kwh(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def _chf(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def _safe_pct(num, den) -> float:
    return float(num) / float(den) * 100 if float(den) > 0 else 0.0


def _pdf_bytes(pdf: FPDF) -> bytes:
    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


class ReportPDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-10)
        self.set_font("Arial", "", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _tx(f"Battery Sizer - page {self.page_no()}"), align="C")


def _add_section_title(pdf: FPDF, title: str, x: float, y: float, w: float):
    pdf.set_xy(x, y)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(w, 8, _tx(title), ln=False)


def _metric_box(pdf: FPDF, x: float, y: float, w: float, h: float, label: str, value: str, sub: str = "", color=BLUE):
    pdf.set_draw_color(*BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 4, y + 4)
    pdf.set_font("Arial", "B", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(w - 8, 4, _tx(label.upper()), ln=True)
    pdf.set_xy(x + 4, y + 11)
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*color)
    pdf.cell(w - 8, 7, _tx(value), ln=True)
    if sub:
        pdf.set_xy(x + 4, y + h - 8)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.cell(w - 8, 4, _tx(sub))


def _info_box(pdf: FPDF, x: float, y: float, w: float, h: float, title: str, text: str, fill=LIGHT_ORANGE, border=SOLEOL_ORANGE):
    pdf.set_draw_color(*border)
    pdf.set_fill_color(*fill)
    pdf.rect(x, y, w, h, style="DF")
    pdf.set_xy(x + 5, y + 4)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*border)
    pdf.cell(w - 10, 5, _tx(title), ln=True)
    pdf.set_xy(x + 5, y + 11)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(w - 10, 4, _tx(text))


def _side_bar(pdf: FPDF, meta, tariff_profile: str):
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 52, 297, style="F")

    pdf.set_xy(8, 12)
    pdf.set_font("Arial", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(36, 8, "SOLEOL", ln=True)
    pdf.set_x(8)
    pdf.set_font("Arial", "", 8)
    pdf.set_text_color(230, 235, 240)
    pdf.cell(36, 5, "ENERGIE SOLAIRE", ln=True)

    pdf.set_xy(8, 42)
    pdf.set_font("Arial", "B", 13)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(36, 6, _tx("ETUDE DE\nDIMENSIONNEMENT\nBATTERIE"))

    infos = [
        ("Client", "A renseigner"),
        ("GRD", tariff_profile),
        ("Periode", f"{getattr(meta, 'coverage_days', 0):.0f} jours"),
        ("Pas de temps", f"{getattr(meta, 'dt_hours', 0) * 60:.0f} min"),
        ("Source", getattr(meta, "vendor", "")),
    ]
    y = 84
    for label, val in infos:
        pdf.set_xy(8, y)
        pdf.set_font("Arial", "B", 7)
        pdf.set_text_color(180, 190, 200)
        pdf.cell(36, 4, _tx(label), ln=True)
        pdf.set_x(8)
        pdf.set_font("Arial", "", 8)
        pdf.set_text_color(255, 255, 255)
        pdf.multi_cell(36, 4, _tx(val))
        y += 14

    pdf.set_xy(8, 255)
    pdf.set_font("Arial", "B", 8)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.multi_cell(36, 4, _tx("L'energie d'aujourd'hui,\noptimisee pour demain."))


def _plot_gain(frontier: pd.DataFrame, best, rec_gain_max: float) -> BytesIO:
    f = frontier.copy()
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(f.Cap_kWh, f.Import_avoided_kWh, "-o", lw=2.2)
    ax.axvline(float(best.Cap_kWh), color="gray", ls="--", lw=1)
    ax.scatter([float(best.Cap_kWh)], [float(best.Import_avoided_kWh)], s=80, zorder=3)
    ax.set_title("Energie valorisee selon la capacite batterie", fontsize=11, weight="bold")
    ax.set_xlabel("Capacite batterie (kWh)")
    ax.set_ylabel("Import evite (kWh/an)")
    ax.grid(alpha=0.25)
    ax.annotate(
        f"{best.Cap_kWh:.0f} kWh\n{best.Import_avoided_kWh:.0f} kWh/an",
        xy=(float(best.Cap_kWh), float(best.Import_avoided_kWh)),
        xytext=(10, 20),
        textcoords="offset points",
        fontsize=8,
        bbox=dict(boxstyle="round", fc="#fff4ef", ec="#e94e35", alpha=0.95),
        arrowprops=dict(arrowstyle="->", color="#e94e35"),
    )
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    buf.seek(0)
    return buf


def _plot_before_after(sim) -> BytesIO:
    labels = ["Import", "Export"]
    before = [sim.import_before, sim.export_before]
    after = [sim.import_after_total, sim.export_after_total]
    x = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(5.8, 3.5))
    ax.bar(x - width / 2, before, width, label="Avant")
    ax.bar(x + width / 2, after, width, label="Apres")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("kWh/an")
    ax.set_title("Import et export avant / apres batterie", fontsize=11, weight="bold")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    buf.seek(0)
    return buf


def _plot_monthly(df, sim) -> BytesIO:
    s = pd.DataFrame(
        {
            "Import avant": df.import_kWh.values,
            "Import apres": sim.import_after,
            "Export avant": df.export_kWh.values,
            "Export apres": sim.export_after,
        },
        index=pd.to_datetime(df.timestamp),
    ).resample("MS").sum()
    months = s.index.strftime("%Y-%m")
    x = np.arange(len(months))
    w = 0.20
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(x - 1.5 * w, s["Import avant"], w, label="Import avant")
    ax.bar(x - 0.5 * w, s["Import apres"], w, label="Import apres")
    ax.bar(x + 0.5 * w, s["Export avant"], w, label="Export avant")
    ax.bar(x + 1.5 * w, s["Export apres"], w, label="Export apres")
    ax.set_xticks(x)
    ax.set_xticklabels(months, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("kWh/mois")
    ax.set_title("Avant / Apres par mois", fontsize=11, weight="bold")
    ax.legend(ncol=4, fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _plot_soc(df, sim, best) -> BytesIO:
    usable = getattr(sim, "usable_capacity_kWh", float(best.Cap_kWh))
    soc_min = getattr(sim, "soc_min_pct", 0.0)
    soc_pct = soc_min + (sim.soc / usable * (100.0 - soc_min)) if usable > 0 else sim.soc * 0
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.plot(pd.to_datetime(df.timestamp), soc_pct, lw=0.7)
    ax.set_ylabel("SOC (%)")
    ax.set_title("Etat de charge de la batterie", fontsize=11, weight="bold")
    ax.grid(alpha=0.20)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _page_1(pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra):
    pdf.add_page()
    _side_bar(pdf, meta, tariff_profile)

    x0 = 58
    pdf.set_xy(x0, 14)
    pdf.set_font("Arial", "B", 17)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(140, 8, _tx("SYNTHESE ENERGETIQUE"), ln=True)

    import_after = sim.import_after_total
    export_after = sim.export_after_total
    import_avoided = sim.import_avoided
    export_avoided = sim.export_stored
    import_reduc = _safe_pct(import_avoided, sim.import_before)
    export_reduc = _safe_pct(export_avoided, sim.export_before)


    # Main metrics
    _metric_box(pdf, x0, 30, 43, 28, "Capacite", f"{best.Cap_kWh:.0f} kWh", color=BLUE)
    _metric_box(pdf, x0 + 47, 30, 43, 28, "Puissance", f"{best.Power_kW:.0f} kW", color=BLUE)
    _metric_box(pdf, x0 + 94, 30, 50, 28, "Energie valorisee", f"{_kwh(import_avoided)} kWh", "Achats reseau evites", color=GREEN)

    y = 67
    w = 34
    h = 26
    gap = 3
    _metric_box(pdf, x0, y, w, h, "Import avant", f"{_kwh(sim.import_before)} kWh", "Depuis le reseau", color=BLUE)
    _metric_box(pdf, x0 + (w + gap), y, w, h, "Import apres", f"{_kwh(import_after)} kWh", "Depuis le reseau", color=BLUE)
    _metric_box(pdf, x0 + 2 * (w + gap), y, w, h, "Import evite", f"{_kwh(import_avoided)} kWh", f"-{import_reduc:.0f} %", color=GREEN)
    _metric_box(pdf, x0 + 3 * (w + gap), y, w, h, "Export avant", f"{_kwh(sim.export_before)} kWh", "Vers le reseau", color=ORANGE)

    y2 = 99
    _metric_box(pdf, x0, y2, w, h, "Export apres", f"{_kwh(export_after)} kWh", "Vers le reseau", color=ORANGE)
    _metric_box(pdf, x0 + (w + gap), y2, w, h, "Export evite", f"{_kwh(export_avoided)} kWh", f"-{export_reduc:.0f} %", color=GREEN)
    _metric_box(pdf, x0 + 2 * (w + gap), y2, w, h, "Surplus capte", f"{sim.surplus_captured:.0%}", "du surplus solaire", color=ORANGE)
    _metric_box(pdf, x0 + 3 * (w + gap), y2, w, h, "Cycles", f"{best.Cycles_per_year:.0f}/an", "equivalents", color=PURPLE)

    conclusion = (
        f"Une batterie de {best.Cap_kWh:.0f} kWh permet de stocker {_kwh(export_avoided)} kWh/an de surplus solaire "
        f"et d'eviter {_kwh(import_avoided)} kWh/an d'achat reseau. "
        f"Cette capacite represente un bon compromis entre energie valorisee et capacite installee. "
        f"Le gain financier estime est indique dans l'analyse detaillee."
    )
    _info_box(pdf, x0, 137, 144, 34, "CONCLUSION ENERGETIQUE", conclusion)

    # Mini gauge
    pdf.set_xy(x0 + 104, 145)
    pdf.set_font("Arial", "B", 18)
    pdf.set_text_color(*GREEN)
    pdf.cell(30, 8, f"+{export_reduc:.0f}%", align="C")
    pdf.set_xy(x0 + 102, 154)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(35, 4, _tx("surplus valorise"), align="C")

    pdf.set_xy(x0, 184)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(145, 4, _tx("Les resultats sont bases sur les mesures reelles import/export et les tarifs renseignes. Les valeurs sont arrondies."))


def _page_2(pdf, df, meta, rec, best, big, sim):
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 9, _tx("Graphiques principaux"), ln=True)

    gain = _plot_gain(rec.frontier, best, rec.gain_max)
    before_after = _plot_before_after(sim)
    monthly = _plot_monthly(df, sim)

    pdf.image(gain, x=10, y=24, w=92)
    pdf.image(before_after, x=110, y=24, w=88)
    pdf.image(monthly, x=10, y=120, w=188)

    pdf.set_xy(10, 275)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(188, 4, _tx("Le graphique principal montre l'energie achetee au reseau qui peut etre evitee selon la capacite batterie. Les graphiques avant/apres montrent l'effet sur les flux reseau."))


def _page_3(pdf, df, meta, best, sim, tariff_profile, tariff_import_ht, tariff_import_bt, tariff_export):
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 9, _tx("Analyse detaillee"), ln=True)

    x = 10
    y = 25
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(*SOLEOL_ORANGE)
    pdf.cell(90, 6, _tx("DETAIL ECONOMIQUE"), ln=True)

    rows = [
        ("Import evite - Haut tarif", f"{_kwh(getattr(sim, 'import_avoided_ht', 0))} kWh x {tariff_import_ht:.2f}", f"{_chf(getattr(sim, 'gain_ht_chf', 0))} CHF"),
        ("Import evite - Bas tarif", f"{_kwh(getattr(sim, 'import_avoided_bt', 0))} kWh x {tariff_import_bt:.2f}", f"{_chf(getattr(sim, 'gain_bt_chf', 0))} CHF"),
        ("Revente perdue", f"{_kwh(getattr(sim, 'export_stored', 0))} kWh x {tariff_export:.2f}", f"-{_chf(getattr(sim, 'export_value_lost_chf', 0))} CHF"),
        ("Gain financier estime", "", f"{_chf(sim.gain_chf)} CHF"),
    ]
    yy = y + 10
    for label, detail, value in rows:
        pdf.set_xy(x, yy)
        pdf.set_font("Arial", "B" if "nettes" in label.lower() else "", 8)
        pdf.set_text_color(*TEXT)
        pdf.cell(70, 6, _tx(label))
        pdf.cell(55, 6, _tx(detail))
        pdf.cell(40, 6, _tx(value), align="R", ln=True)
        yy += 7

    _info_box(
        pdf,
        10,
        70,
        90,
        28,
        "PARAMETRES",
        f"Profil GRD : {tariff_profile}\nRendement batterie : voir parametres de simulation\nPas de temps : {meta.dt_hours * 60:.0f} min\nCouverture : {meta.coverage_days:.0f} jours",
        fill=LIGHT_BG,
        border=BORDER,
    )
    _info_box(
        pdf,
        108,
        70,
        90,
        28,
        "CYCLES BATTERIE",
        f"Cycles equivalents : {best.Cycles_per_year:.0f} cycles/an\nCapacite utile : {getattr(sim, 'usable_capacity_kWh', best.Cap_kWh):.1f} kWh\nSOC minimum : {getattr(sim, 'soc_min_pct', 0):.0f} %",
        fill=LIGHT_GREEN,
        border=GREEN,
    )

    soc = _plot_soc(df, sim, best)
    pdf.image(soc, x=10, y=115, w=188)

    pdf.set_xy(10, 242)
    pdf.set_font("Arial", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(188, 4, _tx("L'etat de charge permet de verifier si la batterie est utilisee regulierement ou si une partie de la capacite reste inactive."))


def _page_4(pdf, rec, best, sim):
    pdf.add_page()
    pdf.set_font("Arial", "B", 15)
    pdf.set_text_color(*TEXT)
    pdf.cell(0, 9, _tx("Tableau des capacites simulees"), ln=True)

    f = rec.frontier.copy().sort_values("Cap_kWh")
    f["Gain_pct"] = f.Gain_CHF / rec.gain_max * 100 if rec.gain_max > 0 else 0
    f["Gain_sup"] = f.Gain_CHF.diff().fillna(0)

    cols = [
        ("Cap. kWh", 18),
        ("Puiss. kW", 18),
        ("Gain CHF/an", 24),
        ("% gain max", 23),
        ("Gain sup.", 22),
        ("Import evite", 32),
        ("Export stocke", 32),
        ("Cycles", 20),
    ]
    x = 10
    y = 25
    pdf.set_fill_color(*SOLEOL_ORANGE)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 7)
    xx = x
    for label, w in cols:
        pdf.rect(xx, y, w, 8, style="F")
        pdf.set_xy(xx, y + 2)
        pdf.cell(w, 4, _tx(label), align="C")
        xx += w

    pdf.set_font("Arial", "", 7)
    max_rows = min(len(f), 24)
    for i, (_, row) in enumerate(f.head(max_rows).iterrows()):
        yy = y + 8 + i * 7
        is_best = abs(float(row.Cap_kWh) - float(best.Cap_kWh)) < 1e-9
        if is_best:
            pdf.set_fill_color(220, 245, 225)
        else:
            pdf.set_fill_color(255, 255, 255) if i % 2 == 0 else pdf.set_fill_color(247, 249, 251)
        pdf.rect(x, yy, sum(w for _, w in cols), 7, style="F")
        pdf.set_text_color(*TEXT)
        vals = [
            f"{row.Cap_kWh:.0f}" + (" *" if is_best else ""),
            f"{row.Power_kW:.0f}",
            _chf(row.Gain_CHF),
            f"{row.Gain_pct:.0f}%",
            _chf(row.Gain_sup),
            _kwh(row.Import_avoided_kWh),
            _kwh(row.Export_stored_kWh),
            f"{row.Cycles_per_year:.0f}",
        ]
        xx = x
        for val, (_, w) in zip(vals, cols):
            pdf.set_xy(xx, yy + 2)
            pdf.cell(w, 4, _tx(val), align="C")
            xx += w

    _info_box(
        pdf,
        10,
        220,
        188,
        26,
        "LECTURE DU TABLEAU",
        f"La ligne marquee * correspond a la capacite recommandee. Elle offre un compromis entre import evite, surplus valorise et taille de batterie. Les capacites plus grandes augmentent peu l\'energie valorisee.",
    )


def generate_battery_report(
    *,
    df,
    meta,
    rec,
    best,
    big,
    sim,
    brand,
    tariff_profile: str,
    tariff_import_ht: float,
    tariff_import_bt: float,
    tariff_export: float,
    gain_share: float,
    gain_max_extra: float,
    cost_life: float = 13,
    sections=None,
) -> bytes:
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)

    _page_1(pdf, df, meta, best, big, sim, tariff_profile, gain_share, gain_max_extra)
    _page_2(pdf, df, meta, rec, best, big, sim)
    _page_3(pdf, df, meta, best, sim, tariff_profile, tariff_import_ht, tariff_import_bt, tariff_export)
    _page_4(pdf, rec, best, sim)

    return _pdf_bytes(pdf)

"""Battery Sizer, Streamlit dashboard.

Pipeline:  upload meter file(s) -> loaders.normalize -> simulation.grid_search
           -> recommend (cycles-aware) -> dashboard + PDF.

UI is bilingual (FR default / EN) via i18n.t; recommend.py emits language-neutral
(code, params) messages rendered here with i18n.msg.

See PROJECT_NOTES.md for the full design rationale.
"""

from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from fpdf import FPDF

from i18n import ERROR_CODES, LANGS, msg, t
from loaders import UnsupportedFormatError, _finalize, load_meter_file
from recommend import BRANDS, recommend
from simulation import grid_search, simulate

st.set_page_config(page_title="Battery Sizer", layout="wide", page_icon="🔋")

# --------------------------------------------------------------------------- language
lang_label = st.sidebar.selectbox("Langue / Language", list(LANGS), index=0, key="lang")
L = LANGS[lang_label]


def T(key: str, **fmt) -> str:
    return t(L, key, **fmt)


# --------------------------------------------------------------------------- sidebar
# Every stateful widget gets a stable key= so its value survives a language switch.
# (Streamlit keys widgets by label by default; translating labels would otherwise reset
# them, and drop the uploaded files, on every language change.)
st.sidebar.header(T("settings_header"))

# Battery brand: sets the healthy cycle band + the warranty sources shown. GoodWe is the
# installer's actual hardware and the default; Huawei here is the meter/data source.
brand_key = st.sidebar.selectbox(
    T("brand_label"), list(BRANDS), index=0,
    format_func=lambda k: BRANDS[k].name, help=T("brand_help"), key="brand",
)
brand = BRANDS[brand_key]
with st.sidebar.expander(T("brand_sources_header")):
    st.caption(T("brand_design_point", cpy=brand.design_cycles_yr))
    st.caption(T(f"brand_note_{brand.key}"))
    for label, url in brand.sources:
        st.markdown(f"- [{label}]({url})")

tariff_import = st.sidebar.number_input(T("tariff_import"), value=0.32, step=0.01,
                                        format="%.2f", key="tariff_import")
tariff_export = st.sidebar.number_input(T("tariff_export"), value=0.08, step=0.01,
                                        format="%.2f", key="tariff_export")
roundtrip_eff = st.sidebar.slider(T("roundtrip"), 0.50, 1.0, 0.92, key="roundtrip")

# Battery cost assumptions, drive the "Payback" tab only (not the recommendation, which is
# price-free on purpose). Defaults are mid Swiss retrofit figures.
with st.sidebar.expander(T("costs_header")):
    cc1, cc2 = st.columns(2)
    cost_price_lo = cc1.number_input(T("cost_price_lo"), 100, 3000, 600, step=50, key="cost_lo")
    cost_price_hi = cc2.number_input(T("cost_price_hi"), 100, 3000, 1000, step=50, key="cost_hi")
    cost_fixed = st.number_input(T("cost_fixed"), 0, 20000, 4000, step=250,
                                 help=T("cost_fixed_help"), key="cost_fixed")
    cost_life = st.number_input(T("cost_life"), 1, 30, 13, key="cost_life")

st.sidebar.markdown(T("search_range"))
c1, c2 = st.sidebar.columns(2)
cap_min = c1.number_input(T("cap_min"), 1, 100, 3, key="cap_min")
cap_max = c2.number_input(T("cap_max"), 1, 200, 20, key="cap_max")
p_min = c1.number_input(T("p_min"), 1, 50, 3, key="p_min")
p_max = c2.number_input(T("p_max"), 1, 100, 10, key="p_max")
cap_step = c1.number_input(T("cap_step"), 1, 20, 1, key="cap_step")
p_step = c2.number_input(T("p_step"), 1, 20, 1, key="p_step")

# Brand-specific key so each brand keeps its own floor and switching brand picks up the
# new brand's default (a shared key would freeze the value across brand changes).
cycles_low = st.sidebar.slider(
    T("cycles_thresh"), 100, 400, int(brand.cycles_low), step=10,
    help=T("cycles_thresh_help"), key=f"cycles_low_{brand.key}",
)
st.sidebar.caption(
    T("healthy_band_caption", low=int(brand.cycles_low), high=int(brand.cycles_high))
)
st.sidebar.info(T("auto_update_hint"))

# PDF report sections: let the installer choose which charts go into the client's PDF, so a
# tailored report can be sent. Keys map to the on-screen tabs; the summary table is always in.
PDF_SECTIONS = ["frontier", "payback", "soc", "cycles", "ba"]
_PDF_SEC_LABEL = {"frontier": "tab_front", "payback": "tab_pay", "soc": "tab_soc",
                  "cycles": "tab_cyc", "ba": "tab_ba"}
with st.sidebar.expander(T("pdf_sections_header")):
    pdf_sections = st.multiselect(
        T("pdf_sections_label"), PDF_SECTIONS, default=PDF_SECTIONS,
        format_func=lambda k: T(_PDF_SEC_LABEL[k]), key="pdf_sections",
    )
    st.caption(T("pdf_sections_hint"))

# --------------------------------------------------------------------------- header
st.title("🔋 Battery Sizer")
st.caption(T("app_caption"))

uploaded = st.file_uploader(
    T("uploader"),
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="uploader",  # stable key -> files survive a language switch
)

if not uploaded:
    st.info(T("drop_prompt"))
    st.stop()


# --------------------------------------------------------------------------- load
@st.cache_data(show_spinner=False)
def _load_one(name: str, data: bytes):
    """Normalize a single uploaded file. Cached by (name, bytes)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_bytes(data)
        return load_meter_file(p)


def _combine(items: dict):
    """Concatenate several already-normalized files into one series (e.g. 12 Huawei months)."""
    frames = [d for d, _ in items.values()]
    vendors = {m.vendor for _, m in items.values()}
    vendor = next(iter(vendors)) if len(vendors) == 1 else "mixed(" + ",".join(sorted(vendors)) + ")"
    sources = "; ".join(m.source for _, m in items.values())
    return _finalize(pd.concat(frames, ignore_index=True), vendor, sources)


# Load each file on its own so one bad file doesn't sink the batch, and so the user can
# pick which file to analyze instead of always getting everything merged together.
loaded: dict = {}
skipped: list[tuple[str, str]] = []
with st.spinner(T("spinner_load")):
    for f in uploaded:
        try:
            loaded[f.name] = _load_one(f.name, f.getvalue())
        except Exception as e:  # UnsupportedFormatError or any parse failure -> report per file
            skipped.append((f.name, str(e)))

if not loaded:
    for name, reason in skipped:
        st.error(T("file_skipped", name=name, reason=reason))
    st.error(T("no_valid_files"))
    st.stop()

# Dataset selector: combine everything (default, the 12-Huawei-months case) or one file.
options = ["__ALL__"] + list(loaded)
choice = st.sidebar.selectbox(
    T("data_select_header"), options, key="dataset",
    format_func=lambda o: T("combine_all", n=len(loaded)) if o == "__ALL__" else o,
)
if choice in loaded:
    df, meta = loaded[choice]
    active_label = choice
else:  # "__ALL__" (or a stale key after files changed) -> combine
    df, meta = _combine(loaded)
    active_label = T("combine_all", n=len(loaded))

if df.empty:
    st.error(T("no_data"))
    st.stop()

st.caption(T("active_dataset", name=active_label))

# --------------------------------------------------------------------------- data quality
imp_tot, exp_tot = float(df.import_kWh.sum()), float(df.export_kWh.sum())
with st.expander(T("dq_expander"), expanded=len(loaded) > 1 or bool(skipped)):
    st.markdown(T("files_loaded_header"))
    for name, (d, m) in loaded.items():
        st.caption(T("file_ok", name=name, vendor=m.vendor, days=f"{m.coverage_days:.0f}",
                     imp=float(d.import_kWh.sum()), exp=float(d.export_kWh.sum())))
    for name, reason in skipped:
        st.caption(T("file_skipped", name=name, reason=reason))
    st.divider()
    q1, q2, q3, q4 = st.columns(4)
    q1.metric(T("dq_source"), meta.vendor)
    q2.metric(T("dq_dt"), T("unit_min", n=f"{meta.dt_hours*60:.0f}"))
    q3.metric(T("dq_coverage"), T("unit_days", n=f"{meta.coverage_days:.0f}"))
    q4.metric(T("dq_points"), f"{meta.n_rows:,}")
    st.write(T("dq_totals", imp=imp_tot, exp=exp_tot))
    if meta.coverage_days < 360:
        st.warning(T("dq_partial"))
if exp_tot <= 0:
    st.error(T("dq_no_surplus"))
    st.stop()

# --------------------------------------------------------------------------- simulate + recommend
caps = list(range(int(cap_min), int(cap_max) + 1, int(cap_step)))
powers = list(range(int(p_min), int(p_max) + 1, int(p_step)))
if not caps or not powers:
    st.error(T("empty_range"))
    st.stop()

with st.spinner(T("spinner_sim", n=len(caps) * len(powers))):
    results = grid_search(
        df.import_kWh.values, df.export_kWh.values, caps, powers,
        meta.dt_hours, roundtrip_eff, tariff_import, tariff_export, meta.coverage_days,
    )
    rec = recommend(results, cycles_low=cycles_low, coverage_days=meta.coverage_days,
                    brand=brand)

best = rec.best
sim = simulate(
    df.import_kWh.values, df.export_kWh.values, best.Cap_kWh, best.Power_kW,
    meta.dt_hours, roundtrip_eff, tariff_import, tariff_export, meta.coverage_days,
)

# --------------------------------------------------------------------------- KPI cards
st.subheader(T("recommendation"))
k = st.columns(5)
k[0].metric(T("kpi_capacity"), f"{best.Cap_kWh:.0f} kWh")
k[1].metric(T("kpi_power"), f"{best.Power_kW:.0f} kW")
k[2].metric(T("kpi_savings"), T("savings_unit", v=f"{best.Gain_CHF:,.0f}"))
k[3].metric(
    T("kpi_cycles"), T("per_year", v=f"{best.Cycles_per_year:.0f}"),
    delta=T("delta_vs_max", v=f"{best.Cycles_per_year - rec.max_gain_pick.Cycles_per_year:+.0f}"),
)
k[4].metric(T("kpi_surplus"), f"{sim.surplus_captured:.0%}")

for code, params in rec.warnings:
    (st.error if code in ERROR_CODES else st.warning)(msg(L, code, params))
for code, params in rec.notes:
    st.caption("• " + msg(L, code, params))

big = rec.max_gain_pick
st.caption(T(
    "compare_caption",
    cap=f"{big.Cap_kWh:.0f}", power=f"{big.Power_kW:.0f}",
    gain=f"{big.Gain_CHF:,.0f}", cyc=f"{big.Cycles_per_year:.0f}",
))

# Surface the rationale behind the cycles floor (defined in recommend.py / PROJECT_NOTES §6):
# why we optimize on cycles at all, and why the threshold sits where it does.
with st.expander(T("why_cycles_header", low=int(cycles_low))):
    st.markdown(T("why_cycles_body", low=int(cycles_low), high=int(brand.cycles_high)))


# --------------------------------------------------------------------------- payback charts
# Two lenses on "how big", ported from battery_sizing_explained.ipynb. The recommendation is
# where the independent money + cycles views agree; each chart corrects a different
# misreading. Kept: whole-system payback U (money optimum) + cycles/yr (price-free use proxy).
def _payback_reason(F, T, rec_cap, cycles_low):
    """Why the recommendation differs from the payback low-point (money optimum).

    The money optimum and the recommended (cycles-healthy) size can land on either side of
    each other, and the *reason* we don't pick the money optimum flips with it:
      - low-point SMALLER than recommended -> it's harder-cycled, but leaves savings on the
        table (the older text wrongly called this "under-used" — e.g. 291 cyc/yr is NOT < 250);
      - low-point LARGER -> genuinely under-cycled (capacity sits idle);
      - same capacity -> the two views agree, nothing to warn about.
    Returns (best_row, annotation_text)."""
    best = F.loc[F.payback_yr.idxmin()]
    best_cap = float(best.Cap_kWh)
    common = dict(cap=f"{best_cap:.0f}", pb=f"{best.payback_yr:.0f}")
    if abs(best_cap - rec_cap) < 0.5:
        text = T("pay_best_annot_agree", **common)
    elif best_cap < rec_cap:
        rec_row = F.loc[(F.Cap_kWh - rec_cap).abs() < 0.5]
        gap = float(rec_row.Gain_CHF.iloc[0]) - float(best.Gain_CHF) if not rec_row.empty else 0.0
        text = T("pay_best_annot_undersized", gap=f"{max(gap, 0):,.0f}",
                 rec=f"{rec_cap:.0f}", **common)
    else:
        text = T("pay_best_annot_oversized", cyc=f"{best.Cycles_per_year:.0f}",
                 low=int(cycles_low), **common)
    return best, text


def _fig_payback(F, T, life, rec_cap, cycles_low):
    """Lens 3 — whole-system payback (fixed install + modules). U-shaped: 1 kWh and 20 kWh
    both lose. The least-bad trough is the money-optimal size; the recommended vline is the
    cycles-healthy pick — the two annotations make the distinction explicit in the viz."""
    fig = go.Figure(go.Scatter(
        x=F.Cap_kWh, y=F.payback_yr, mode="lines+markers", line=dict(color="#7c3aed", width=3),
        hovertemplate=T("pay_pb_hover", cap="%{x:.0f}", pb="%{y:.1f}") + "<extra></extra>"))
    fig.add_hline(y=life, line_dash="dash", line_color="#dc2626",
                  annotation_text=T("pay_life_line", life=life),
                  annotation_position="bottom right")
    best, best_text = _payback_reason(F, T, rec_cap, cycles_low)
    # The orange box (money optimum) sits up-LEFT of the trough; the green recommended label
    # sits up-RIGHT of its line, so the two never overlap regardless of which side the
    # recommendation lands on.
    fig.add_annotation(
        x=float(best.Cap_kWh), y=float(best.payback_yr),
        text=best_text, xanchor="right",
        showarrow=True, arrowhead=2, ax=-50, ay=-55, bgcolor="#fff7ed", bordercolor="#f97316",
        borderwidth=1, borderpad=4, font=dict(color="black", size=11))
    fig.add_vline(x=rec_cap, line_color="#16a34a",
                  annotation_text=T("pay_rec_annot", cap=f"{rec_cap:.0f}"),
                  annotation_position="top right",
                  annotation_font=dict(color="black", size=11),
                  annotation_bgcolor="#dcfce7", annotation_bordercolor="#16a34a",
                  annotation_borderwidth=1, annotation_borderpad=3)
    fig.update_layout(title=T("pay_pb_title"), xaxis=dict(title=T("axis_capacity"), dtick=2),
                      yaxis_title=T("pay_pb_axis"), template="plotly_white",
                      hoverlabel=dict(bgcolor="#1f2937", font=dict(color="white", size=12),
                                      bordercolor="#7c3aed"),
                      height=380, margin=dict(t=60, r=50, l=60, b=50))
    return fig


def _fig_cycles(F, T, cycles_low, cycles_high, rec_cap):
    """Lens 4 — cycles/yr + capacity cycled per day, with the healthy band. The price-free
    proxy for 'is this capacity actually used?' — the floor recommend.py optimizes on."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=F.Cap_kWh, y=F.Cycles_per_year, name=T("pay_cycles_use"),
        mode="lines+markers", line=dict(color="#0891b2", width=3),
        hovertemplate=T("pay_cycles_hover", cap="%{x:.0f}", cyc="%{y:.0f}") + "<extra></extra>",
        cliponaxis=False), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=F.Cap_kWh, y=F.frac_full_per_day, name=T("pay_cycles_frac"),
        mode="lines+markers", line=dict(color="#65a30d", width=2, dash="dot"),
        hovertemplate=T("pay_cycles_hover2", cap="%{x:.0f}", frac="%{y:.2f}") + "<extra></extra>",
        cliponaxis=False), secondary_y=True)
    fig.add_hrect(y0=cycles_low, y1=cycles_high, fillcolor="#86efac", opacity=0.25, line_width=0,
                  annotation_text=T("pay_cycles_healthy", low=int(cycles_low), high=int(cycles_high)),
                  annotation_position="top left", secondary_y=False)
    fig.add_hline(y=150, line_dash="dash", line_color="#dc2626",
                  annotation_text=T("pay_cycles_oversized"),
                  annotation_position="bottom left", secondary_y=False)
    fig.add_vline(x=rec_cap, line_color="#16a34a",
                  annotation_text=T("pay_rec_annot", cap=f"{rec_cap:.0f}"),
                  annotation_position="top right",
                  annotation_font=dict(color="black", size=11),
                  annotation_bgcolor="#dcfce7", annotation_bordercolor="#16a34a",
                  annotation_borderwidth=1, annotation_borderpad=3)
    fig.update_yaxes(title_text=T("axis_cycles"), secondary_y=False, color="#0891b2")
    fig.update_yaxes(title_text=T("pay_cycles_y2"), secondary_y=True, color="#65a30d")
    fig.update_layout(xaxis=dict(title=T("axis_capacity"), dtick=2), template="plotly_white",
                      hoverlabel=dict(bgcolor="#1f2937", font=dict(color="white", size=12),
                                      bordercolor="#0891b2"),
                      height=380, legend=dict(orientation="h", y=1.13),
                      margin=dict(t=60, r=70, l=60, b=50))
    return fig


# --------------------------------------------------------------------------- charts
tab_front, tab_pay, tab_soc, tab_cyc, tab_ba = st.tabs(
    [T("tab_front"), T("tab_pay"), T("tab_soc"), T("tab_cyc"), T("tab_ba")]
)

with tab_front:
    f = rec.frontier
    fig = go.Figure()
    fig.add_hrect(y0=brand.cycles_low, y1=brand.cycles_high, line_width=0,
                  fillcolor="green", opacity=0.08, yref="y2",
                  annotation_text=T("healthy_band"), annotation_position="top left")
    fig.add_trace(go.Scatter(x=f.Cap_kWh, y=f.Gain_CHF, name=T("legend_gain"),
                             mode="lines+markers", line=dict(color="#2563eb")))
    fig.add_trace(go.Scatter(x=f.Cap_kWh, y=f.Cycles_per_year, name=T("legend_cycles"),
                             mode="lines+markers", line=dict(color="#16a34a", dash="dot"), yaxis="y2"))
    fig.add_trace(go.Scatter(x=[best.Cap_kWh], y=[best.Gain_CHF], name=T("legend_recommended"),
                             mode="markers", marker=dict(size=15, color="#2563eb", symbol="star")))
    fig.add_trace(go.Scatter(x=[big.Cap_kWh], y=[big.Gain_CHF], name=T("legend_maxgain"),
                             mode="markers", marker=dict(size=12, color="#dc2626", symbol="x")))
    fig.update_layout(
        xaxis_title=T("axis_capacity"), yaxis_title=T("axis_gain"),
        yaxis2=dict(title=T("axis_cycles"), overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.12), height=460, margin=dict(t=40),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        f.assign(**{T("col_pct_max"): (f.Gain_CHF / rec.gain_max * 100).round(1)})[
            ["Cap_kWh", "Power_kW", "Gain_CHF", T("col_pct_max"), "Cycles_per_year"]
        ].round(1),
        use_container_width=True, hide_index=True,
    )

with tab_pay:
    # Two size lenses (notebook §29): whole-system payback (money optimum) + cycles/yr
    # (price-free use proxy). The recommendation is where they agree; each corrects a
    # different misreading of a single money view.
    pay_caps = list(range(1, int(cap_max) + 1))
    pay_gs = grid_search(df.import_kWh.values, df.export_kWh.values, pay_caps, powers,
                         meta.dt_hours, roundtrip_eff, tariff_import, tariff_export,
                         meta.coverage_days)
    f = pay_gs.loc[pay_gs.groupby("Cap_kWh")["Gain_CHF"].idxmax()] \
              .sort_values("Cap_kWh").reset_index(drop=True)
    f["frac_full_per_day"] = f.Cycles_per_year / 365.0
    price_mid = (cost_price_lo + cost_price_hi) / 2
    f["capex"] = cost_fixed + price_mid * f.Cap_kWh
    f["payback_yr"] = f.capex / f.Gain_CHF.where(f.Gain_CHF > 0, np.nan)
    rec_cap = float(best.Cap_kWh)
    sel = f.Cap_kWh == rec_cap
    rec_pb = float(f.payback_yr[sel].iloc[0]) if sel.any() and bool(f.payback_yr[sel].notna().any()) else float("nan")

    # --- supportive verdict + metric strip, pointing at the one recommended size ---
    st.success(T("pay_verdict", rec=f"{rec_cap:.0f}", cyc=f"{best.Cycles_per_year:.0f}"))
    m = st.columns(3)
    m[0].metric(T("pay_kpi_rec"), f"{rec_cap:.0f} kWh")
    m[1].metric(T("kpi_savings"), T("savings_unit", v=f"{best.Gain_CHF:,.0f}"))
    m[2].metric(T("pay_kpi_payback"), "n/a" if np.isnan(rec_pb) else T("pay_yr_val", v=f"{rec_pb:.0f}"))

    # --- Lens 1: whole-system payback U-curve (fixed install + modules) ---
    st.plotly_chart(_fig_payback(f, T, cost_life, rec_cap, cycles_low), use_container_width=True)
    pb_cap = float(f.loc[f.payback_yr.idxmin(), "Cap_kWh"])
    st.caption(T("pay_pb_caption", pb=f"{pb_cap:.0f}", rec=f"{rec_cap:.0f}"))

    # --- Lens 2: cycles/yr + capacity-use (why the floor is a price-free shortcut) ---
    st.plotly_chart(_fig_cycles(f, T, cycles_low, brand.cycles_high, rec_cap), use_container_width=True)
    st.caption(T("pay_cycles_caption", low=int(cycles_low)))

ts = df.timestamp.values
with tab_soc:
    soc_pct = sim.soc / best.Cap_kWh * 100.0
    fig = go.Figure(go.Scatter(x=ts, y=soc_pct, mode="lines", line=dict(color="#7c3aed", width=1)))
    fig.update_layout(yaxis_title=T("axis_soc"), xaxis_title=T("axis_date"), height=420,
                      title=T("soc_title", cap=f"{best.Cap_kWh:.0f}", power=f"{best.Power_kW:.0f}"))
    st.plotly_chart(fig, use_container_width=True)

with tab_cyc:
    discharge = df.import_kWh.values - sim.import_after
    cum_cycles = np.cumsum(discharge) / best.Cap_kWh
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts, y=cum_cycles, mode="lines", name=T("cyc_legend_cum"),
                             line=dict(color="#16a34a")))
    # straight reference line = perfectly steady cycling
    fig.add_trace(go.Scatter(x=[ts[0], ts[-1]], y=[0, cum_cycles[-1]], mode="lines",
                             name=T("cyc_legend_steady"), line=dict(color="#9ca3af", dash="dash")))
    fig.update_layout(yaxis_title=T("cyc_axis"), xaxis_title=T("axis_date"), height=420,
                      legend=dict(orientation="h", y=1.1), title=T("cyc_title"))
    st.plotly_chart(fig, use_container_width=True)

with tab_ba:
    s = pd.DataFrame({"import_kWh": df.import_kWh.values, "export_kWh": df.export_kWh.values,
                      "import_after": sim.import_after, "export_after": sim.export_after},
                     index=pd.to_datetime(df.timestamp)).resample("MS").sum()
    # Categorical month labels (not datetimes): grouped bars on a date axis render as
    # near-invisible slivers, so use "YYYY-MM" strings to force a category axis.
    months = s.index.strftime("%Y-%m")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=months, y=s.import_kWh, name=T("ba_import_before"), marker_color="#fca5a5"))
    fig.add_trace(go.Bar(x=months, y=s.import_after, name=T("ba_import_after"), marker_color="#dc2626"))
    fig.add_trace(go.Bar(x=months, y=s.export_kWh, name=T("ba_export_before"), marker_color="#bfdbfe"))
    fig.add_trace(go.Bar(x=months, y=s.export_after, name=T("ba_export_after"), marker_color="#2563eb"))
    fig.update_layout(barmode="group", height=440, yaxis_title=T("ba_axis"),
                      xaxis=dict(type="category"), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- PDF
def _tx(s) -> str:
    """Make text safe for the PDF core (Latin-1) font: swap common Unicode, drop the rest."""
    repl = {"—": "-", "–": "-", "→": "->", "≥": ">=", "≤": "<=", "≈": "~",
            "•": "-", "✅": "", "⚠️": "!", "’": "'", "œ": "oe", "…": "..."}
    s = str(s)
    for k, v in repl.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _annot_plain(s: str) -> str:
    """Render a Plotly annotation string for matplotlib: HTML <br>/&lt;/&gt; -> plain text."""
    return _tx(str(s).replace("<br>", "\n").replace("&lt;", "<").replace("&gt;", ">"))


def _pdf_text(s: str) -> str:
    """A prose string for the PDF body: drop markdown bold markers, then Latin-1-clean."""
    return _tx(str(s).replace("**", ""))


def _build_pdf(sections) -> bytes:
    # Matplotlib renders for the PDF (reliable, no headless-browser dependency). Only the
    # charts ticked in the sidebar are built and embedded; the summary table is always in.
    figs: dict = {}
    tindex = pd.to_datetime(df.timestamp)

    if "frontier" in sections:
        fig1, ax = plt.subplots(figsize=(9, 3.2))
        ax.plot(rec.frontier.Cap_kWh, rec.frontier.Gain_CHF, "b-o", label=T("legend_gain"))
        ax2 = ax.twinx()
        ax2.plot(rec.frontier.Cap_kWh, rec.frontier.Cycles_per_year, "g--s", label=T("legend_cycles"))
        ax2.axhspan(brand.cycles_low, brand.cycles_high, color="green", alpha=0.08)
        ax.axvline(best.Cap_kWh, color="k", ls=":")
        ax.set_xlabel(T("pdf_fig1_xlabel")); ax.set_ylabel(T("pdf_fig1_ylabel"))
        ax2.set_ylabel(T("pdf_fig1_y2label"))
        ax.set_title(T("pdf_fig1_title")); fig1.tight_layout()
        figs["frontier"] = [(fig1, T("pdf_cap_frontier"))]

    if "ba" in sections:
        fig2, axb = plt.subplots(figsize=(9, 3.2))
        s = pd.DataFrame({"i0": df.import_kWh.values, "i1": sim.import_after,
                          "e0": df.export_kWh.values, "e1": sim.export_after},
                         index=tindex).resample("MS").sum()
        # Grouped bars on a categorical month axis (like the dashboard tab). Lines failed for
        # short series, a single-month dataset has one point and draws no visible segment.
        months = s.index.strftime("%Y-%m")
        x = np.arange(len(months)); w = 0.2
        axb.bar(x - 1.5 * w, s.i0, w, label=T("ba_import_before"), color="#fca5a5")
        axb.bar(x - 0.5 * w, s.i1, w, label=T("ba_import_after"), color="#dc2626")
        axb.bar(x + 0.5 * w, s.e0, w, label=T("ba_export_before"), color="#bfdbfe")
        axb.bar(x + 1.5 * w, s.e1, w, label=T("ba_export_after"), color="#2563eb")
        axb.set_xticks(x); axb.set_xticklabels(months, rotation=45, ha="right", fontsize=7)
        axb.legend(fontsize=7); axb.set_ylabel(T("pdf_fig2_ylabel"))
        axb.set_title(T("pdf_fig2_title")); fig2.tight_layout()
        figs["ba"] = [(fig2, T("pdf_cap_ba"))]

    if "soc" in sections:
        # State of charge over time (matches the "État de charge" tab).
        fig3, axc = plt.subplots(figsize=(9, 2.8))
        axc.plot(tindex, sim.soc / best.Cap_kWh * 100.0, color="#7c3aed", lw=0.6)
        axc.set_ylabel(T("axis_soc")); axc.set_xlabel(T("axis_date"))
        axc.set_title(T("soc_title", cap=f"{best.Cap_kWh:.0f}", power=f"{best.Power_kW:.0f}"))
        fig3.tight_layout()
        figs["soc"] = [(fig3, T("pdf_cap_soc"))]

    if "cycles" in sections:
        # Cumulative equivalent cycles, with the steady-pace reference line (the "diagonal").
        fig4, axd = plt.subplots(figsize=(9, 2.8))
        cum_cycles = np.cumsum(df.import_kWh.values - sim.import_after) / best.Cap_kWh
        axd.plot(tindex, cum_cycles, color="#16a34a", label=T("cyc_legend_cum"))
        axd.plot([tindex.iloc[0], tindex.iloc[-1]], [0, cum_cycles[-1]],
                 color="#9ca3af", ls="--", label=T("cyc_legend_steady"))
        axd.set_ylabel(T("cyc_axis")); axd.set_xlabel(T("axis_date"))
        axd.set_title(T("cyc_title")); axd.legend(fontsize=7)
        fig4.tight_layout()
        figs["cycles"] = [(fig4, T("pdf_cap_cyc"))]

    if "payback" in sections:
        # Whole-system payback U-curve (matches the "Rentabilite" tab). Self-contained: recompute
        # the frame so the PDF never depends on whether the tab was rendered. The money-optimum
        # annotation uses the same dynamic reason as the dashboard (_payback_reason), so the PDF
        # no longer ships the bare "least-bad" label.
        pay_gs2 = grid_search(df.import_kWh.values, df.export_kWh.values,
                              list(range(1, int(cap_max) + 1)), powers,
                              meta.dt_hours, roundtrip_eff, tariff_import, tariff_export,
                              meta.coverage_days)
        fp = pay_gs2.loc[pay_gs2.groupby("Cap_kWh")["Gain_CHF"].idxmax()] \
                   .sort_values("Cap_kWh").reset_index(drop=True)
        _price_mid = (cost_price_lo + cost_price_hi) / 2
        fp["payback_yr"] = (cost_fixed + _price_mid * fp.Cap_kWh) \
            / fp.Gain_CHF.where(fp.Gain_CHF > 0, np.nan)
        fig5, axp = plt.subplots(figsize=(9, 3.4))
        axp.plot(fp.Cap_kWh, fp.payback_yr, "-o", color="#7c3aed", lw=2, ms=4)
        axp.axhline(cost_life, color="#dc2626", ls="--", lw=1)
        axp.text(fp.Cap_kWh.iloc[-1], cost_life, _tx(T("pay_life_line", life=cost_life)),
                 color="#dc2626", fontsize=7, ha="right", va="bottom")
        pb_row, pb_text = _payback_reason(fp, T, float(best.Cap_kWh), cycles_low)
        pb_x, pb_y = float(pb_row.Cap_kWh), float(pb_row.payback_yr)
        axp.plot([pb_x], [pb_y], "o", color="#f97316", ms=7)
        # Box up-LEFT of the trough; green recommended label up-RIGHT of its line, so the two
        # never overlap (same separation as the on-screen chart).
        axp.annotate(_annot_plain(pb_text), xy=(pb_x, pb_y), xytext=(-12, 28),
                     textcoords="offset points", fontsize=6.5, color="#9a3412",
                     ha="right", va="bottom",
                     bbox=dict(boxstyle="round", fc="#fff7ed", ec="#f97316", lw=0.8),
                     arrowprops=dict(arrowstyle="->", color="#f97316"))
        axp.axvline(best.Cap_kWh, color="#16a34a", ls=":", lw=1.5)
        axp.text(best.Cap_kWh, axp.get_ylim()[1], _tx(T("pay_rec_line", cap=f"{best.Cap_kWh:.0f}")),
                 color="#16a34a", fontsize=7, ha="left", va="top")
        axp.set_xlabel(T("axis_capacity")); axp.set_ylabel(T("pay_pb_axis"))
        axp.set_title(T("pay_pb_title")); fig5.tight_layout()

        # 2nd payback lens (matches the cycles/yr chart under the on-screen Payback tab): is
        # each kWh of capacity actually cycled? Price-free proxy for "well used".
        fig6, axq = plt.subplots(figsize=(9, 3.0))
        l1, = axq.plot(fp.Cap_kWh, fp.Cycles_per_year, "-o", color="#0891b2", lw=2, ms=4,
                       label=T("pay_cycles_use"))
        axq.axhspan(cycles_low, brand.cycles_high, color="#86efac", alpha=0.25)
        axq.text(fp.Cap_kWh.iloc[0], (cycles_low + brand.cycles_high) / 2,
                 _tx(T("pay_cycles_healthy", low=int(cycles_low), high=int(brand.cycles_high))),
                 fontsize=6, color="#15803d", va="center")
        axq.axhline(150, color="#dc2626", ls="--", lw=1)
        axq.text(fp.Cap_kWh.iloc[-1], 150, _tx(T("pay_cycles_oversized")),
                 fontsize=6, color="#dc2626", ha="right", va="bottom")
        axq.axvline(best.Cap_kWh, color="#16a34a", ls=":", lw=1.5)
        axq.text(best.Cap_kWh, axq.get_ylim()[1], _tx(T("pay_rec_line", cap=f"{best.Cap_kWh:.0f}")),
                 color="#16a34a", fontsize=7, ha="left", va="top")
        axq.set_xlabel(T("axis_capacity")); axq.set_ylabel(T("axis_cycles"), color="#0891b2")
        axq2 = axq.twinx()
        l2, = axq2.plot(fp.Cap_kWh, fp.Cycles_per_year / 365.0, ":", color="#65a30d", lw=1.5,
                        label=T("pay_cycles_frac"))
        axq2.set_ylabel(T("pay_cycles_y2"), color="#65a30d")
        axq.legend([l1, l2], [l1.get_label(), l2.get_label()], fontsize=7, loc="upper right")
        axq.set_title(T("pdf_cycles_title")); fig6.tight_layout()

        figs["payback"] = [
            (fig5, T("pay_pb_caption", pb=f"{pb_x:.0f}", rec=f"{best.Cap_kWh:.0f}")),
            (fig6, T("pay_cycles_caption", low=int(cycles_low))),
        ]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16); pdf.cell(0, 10, _tx(T("pdf_title")), ln=True, align="C")
    pdf.ln(4); pdf.set_font("Arial", "B", 12); pdf.cell(0, 8, _tx(T("pdf_section")), ln=True)
    pdf.set_font("Arial", "", 11)
    rows = [
        (T("pdf_capacity"), f"{best.Cap_kWh:.0f} kWh"),
        (T("pdf_power"), f"{best.Power_kW:.0f} kW"),
        (T("pdf_savings"), T("pdf_savings_val", v=f"{best.Gain_CHF:,.0f}")),
        (T("pdf_brand"), brand.name),
        (T("pdf_cycles"), T("pdf_cycles_val", cyc=f"{best.Cycles_per_year:.0f}",
                            low=int(brand.cycles_low), high=int(brand.cycles_high))),
        (T("pdf_import_avoided"), T("pdf_energy_val", kwh=f"{sim.import_avoided:,.0f}",
                                    pct=f"{sim.import_reduction:.0%}")),
        (T("pdf_surplus"), T("pdf_energy_val", kwh=f"{sim.export_stored:,.0f}",
                             pct=f"{sim.surplus_captured:.0%}")),
        (T("pdf_compare"), T("pdf_compare_val", cap=f"{big.Cap_kWh:.0f}",
                             gain=f"{big.Gain_CHF:,.0f}", cyc=f"{big.Cycles_per_year:.0f}")),
        (T("pdf_source"), T("pdf_source_val", vendor=meta.vendor, days=f"{meta.coverage_days:.0f}")),
    ]
    for a, b in rows:
        pdf.cell(70, 7, _tx(a)); pdf.cell(0, 7, _tx(b), ln=True)
    pdf.set_text_color(180, 0, 0)
    for code, params in rec.warnings:
        pdf.set_x(pdf.l_margin)  # multi_cell can leave x at the right edge -> reset each time
        pdf.multi_cell(0, 6, _tx("! " + msg(L, code, params)))
    pdf.set_text_color(0, 0, 0); pdf.ln(1)

    # Plain-language verdict so a buyer reading the PDF gets the reasoning, not just charts.
    pdf.set_font("Arial", "", 10); pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, _pdf_text(T("pay_verdict", rec=f"{best.Cap_kWh:.0f}",
                                     cyc=f"{best.Cycles_per_year:.0f}")))
    pdf.set_font("Arial", "", 11); pdf.ln(2)

    # Order matches the on-screen tabs: frontier, payback (U + cycles lens), SOC, cumulative
    # cycles, before/after. Only the selected sections were built; each figure gets a caption
    # below it so the report explains itself.
    for key in ("frontier", "payback", "soc", "cycles", "ba"):
        for fig, caption in figs.get(key, []):
            buf = BytesIO(); fig.savefig(buf, format="png", dpi=120); buf.seek(0)
            w_mm = 186
            h_mm = w_mm * fig.get_size_inches()[1] / fig.get_size_inches()[0]
            if pdf.get_y() + h_mm + 16 > pdf.h - pdf.b_margin:  # fig + caption -> new page
                pdf.add_page()
            pdf.image(buf, x=12, w=w_mm); pdf.ln(1)
            if caption:
                pdf.set_font("Arial", "I", 8); pdf.set_text_color(90, 90, 90)
                pdf.set_x(pdf.l_margin); pdf.multi_cell(186, 4, _pdf_text(caption))
                pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 11)
            pdf.ln(2)
            plt.close(fig)
    out = pdf.output()
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


st.divider()
if not pdf_sections:
    st.caption(T("pdf_sections_empty"))
st.download_button(T("pdf_button"), _build_pdf(pdf_sections),
                   file_name=T("pdf_filename"), mime="application/pdf")

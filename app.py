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
from report import generate_battery_report
from grd_profiles import GRD_PROFILES

st.set_page_config(page_title="Battery Sizer", layout="wide", page_icon="🔋")


st.markdown(
    """
    <style>
    :root {
        --card-bg: rgba(17, 24, 39, 0.72);
        --card-border: rgba(148, 163, 184, 0.20);
        --muted: #94a3b8;
        --blue: #3b82f6;
        --green: #4ade80;
        --orange: #fb923c;
        --purple: #a855f7;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(148, 163, 184, 0.18);
    }
    .mar-summary-title {
        font-size: 1.65rem;
        font-weight: 800;
        letter-spacing: .02em;
        margin: 1.4rem 0 .8rem 0;
        text-transform: uppercase;
    }
    .mar-card-grid-5 {
        display: grid;
        grid-template-columns: repeat(5, minmax(150px, 1fr));
        gap: 14px;
        margin-bottom: 14px;
    }
    .mar-card-grid-6 {
        display: grid;
        grid-template-columns: repeat(6, minmax(130px, 1fr));
        gap: 12px;
        margin-bottom: 14px;
    }
    .mar-card {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.88));
        border: 1px solid var(--card-border);
        border-radius: 14px;
        padding: 16px 18px;
        min-height: 128px;
        box-shadow: 0 14px 35px rgba(0,0,0,.22);
    }
    .mar-card.small {
        min-height: 118px;
        padding: 14px 16px;
    }
    .mar-label {
        color: #e5e7eb;
        font-size: .94rem;
        font-weight: 700;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .mar-icon {
        font-size: 1.35rem;
        line-height: 1;
    }
    .mar-value {
        font-size: 2.05rem;
        font-weight: 800;
        line-height: 1.05;
        white-space: nowrap;
    }
    .mar-value.small {
        font-size: 1.8rem;
    }
    .mar-sub {
        color: var(--muted);
        font-size: .85rem;
        margin-top: 8px;
    }
    .mar-blue { color: var(--blue); }
    .mar-green { color: var(--green); }
    .mar-orange { color: var(--orange); }
    .mar-purple { color: var(--purple); }
    .mar-autoconso {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.90));
        border: 1px solid var(--card-border);
        border-radius: 14px;
        padding: 18px 22px;
        margin: 8px 0 20px 0;
        box-shadow: 0 14px 35px rgba(0,0,0,.22);
    }
    .mar-autoconso-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 18px;
        text-align: center;
        margin-top: 10px;
    }
    .mar-autoconso-cell {
        border-left: 1px solid rgba(148, 163, 184, 0.25);
    }
    .mar-autoconso-cell:first-child {
        border-left: none;
    }
    .mar-pill {
        display: inline-block;
        padding: 4px 9px;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 700;
        background: rgba(34, 197, 94, .15);
        color: #86efac;
        margin-top: 8px;
    }
    @media (max-width: 1100px) {
        .mar-card-grid-5, .mar-card-grid-6 {
            grid-template-columns: repeat(2, minmax(160px, 1fr));
        }
        .mar-autoconso-grid {
            grid-template-columns: 1fr;
        }
        .mar-autoconso-cell {
            border-left: none;
            border-top: 1px solid rgba(148, 163, 184, 0.25);
            padding-top: 12px;
        }
        .mar-autoconso-cell:first-child {
            border-top: none;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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

# Marque batterie masquée pour l'instant.
# Le moteur garde GoodWe comme référence interne pour les seuils techniques,
# mais l'utilisateur ne voit plus le choix de marque ni les sources cycles.
brand = BRANDS["goodwe"]

st.sidebar.markdown("**Données**")
unit_choice = st.sidebar.selectbox(
    "Unité des données import/export",
    ["Automatique", "kWh", "kW", "Wh", "W"],
    index=0,
    key="data_unit",
    help=(
        "Automatique utilise l'unité détectée selon le fichier. "
        "Choisir kW/W si les colonnes sont des puissances moyennes par intervalle ; "
        "choisir kWh/Wh si les colonnes sont déjà des énergies par intervalle."
    ),
)
loader_unit = "auto" if unit_choice == "Automatique" else unit_choice
st.sidebar.caption(
    "kW/W = puissance moyenne convertie en kWh avec le pas de temps détecté. "
    "kWh/Wh = énergie déjà mesurée par intervalle."
)

st.sidebar.markdown("**Tarifs énergie**")

tariff_profiles = GRD_PROFILES


tariff_profile = st.sidebar.selectbox(
    "Profil tarifaire GRD",
    list(tariff_profiles),
    index=0,
    key="tariff_profile",
)
profile = tariff_profiles[tariff_profile]

if profile.get("needs_verification", False):
    st.sidebar.warning(
        "Tarifs préremplis à vérifier : renseigne les valeurs exactes du contrat client "
        "ou mets à jour grd_profiles.py."
    )

manual_tariffs = st.sidebar.checkbox(
    "Modifier manuellement les tarifs",
    value=True,
    key=f"manual_tariffs_{tariff_profile}",
)

tariff_import_ht = st.sidebar.number_input(
    "Tarif achat haut tarif (CHF/kWh)",
    value=float(profile["ht"]),
    step=0.01,
    format="%.2f",
    key=f"tariff_import_ht_{tariff_profile}",
    disabled=not manual_tariffs,
)
tariff_import_bt = st.sidebar.number_input(
    "Tarif achat bas tarif (CHF/kWh)",
    value=float(profile["bt"]),
    step=0.01,
    format="%.2f",
    key=f"tariff_import_bt_{tariff_profile}",
    disabled=not manual_tariffs,
)
tariff_export = st.sidebar.number_input(
    "Tarif rachat / revente (CHF/kWh)",
    value=float(profile["export"]),
    step=0.01,
    format="%.2f",
    key=f"tariff_export_{tariff_profile}",
    disabled=not manual_tariffs,
)

if tariff_profile == "Personnalise":
    with st.sidebar.expander("Plages haut tarif personnalisées", expanded=True):
        ht1_start = st.number_input("HT 1 début", 0.0, 24.0, 7.0, step=0.5, format="%.1f", key="custom_ht1_start")
        ht1_end = st.number_input("HT 1 fin", 0.0, 24.0, 12.0, step=0.5, format="%.1f", key="custom_ht1_end")
        use_ht2 = st.checkbox("Ajouter une 2e plage HT", value=True, key="custom_use_ht2")
        if use_ht2:
            ht2_start = st.number_input("HT 2 début", 0.0, 24.0, 17.0, step=0.5, format="%.1f", key="custom_ht2_start")
            ht2_end = st.number_input("HT 2 fin", 0.0, 24.0, 23.0, step=0.5, format="%.1f", key="custom_ht2_end")
            high_tariff_periods = ((float(ht1_start), float(ht1_end)), (float(ht2_start), float(ht2_end)))
        else:
            high_tariff_periods = ((float(ht1_start), float(ht1_end)),)

        weekend_low_tariff = st.checkbox(
            "Week-end entièrement en bas tarif",
            value=False,
            key="custom_weekend_low_tariff",
        )
else:
    with st.sidebar.expander(f"Plages tarifaires {tariff_profile}", expanded=False):
        st.caption(profile["description"])
        st.caption(f"Source / note : {profile.get('source', 'à vérifier')}")
    high_tariff_periods = profile["periods"]
    weekend_low_tariff = bool(profile["weekend_low"])

tariff_import = tariff_import_ht  # compatibilité avec les anciens textes/graphes

roundtrip_eff = st.sidebar.slider(T("roundtrip"), 0.50, 1.0, 0.92, key="roundtrip")

# Coûts batterie masqués : le dimensionnement principal utilise uniquement
# les flux import/export et les tarifs HT/BT/rachat.
# Ces valeurs restent définies pour ne pas casser les anciens graphiques/PDF.
cost_price_lo = 600
cost_price_hi = 1000
cost_fixed = 4000
cost_life = 13

st.sidebar.markdown(T("search_range"))
c1, c2 = st.sidebar.columns(2)
cap_min = c1.number_input(T("cap_min"), 1, 100, 3, key="cap_min")
cap_max = c2.number_input(T("cap_max"), 1, 200, 80, key="cap_max")
auto_cap_max = st.sidebar.checkbox(
    "Cap. max automatique",
    value=True,
    key="auto_cap_max",
    help=(
        "Calcule automatiquement une limite de recherche suffisante pour atteindre le plateau "
        "de gain. La valeur Cap. max sert alors seulement de limite de sécurité."
    ),
)
p_min = c1.number_input(T("p_min"), 1, 50, 3, key="p_min")
p_max = c2.number_input(T("p_max"), 1, 100, 10, key="p_max")
cap_step = c1.number_input(T("cap_step"), 1, 20, 1, key="cap_step")
p_step = c2.number_input(T("p_step"), 1, 20, 1, key="p_step")

# Brand-specific key so each brand keeps its own floor and switching brand picks up the
# new brand's default (a shared key would freeze the value across brand changes).
cycles_low = st.sidebar.slider(
    T("cycles_thresh"), 100, 400, int(brand.cycles_low), step=10,
    help=T("cycles_thresh_help"), key="cycles_low",
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
def _load_one(name: str, data: bytes, data_unit: str):
    """Normalize a single uploaded file. Cached by (name, bytes, data_unit)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_bytes(data)
        return load_meter_file(p, data_unit=data_unit)


def _combine(items: dict):
    """Concatenate several already-normalized files into one series (e.g. 12 Huawei months)."""
    frames = [d for d, _ in items.values()]
    vendors = {m.vendor for _, m in items.values()}
    vendor = next(iter(vendors)) if len(vendors) == 1 else "mixed(" + ",".join(sorted(vendors)) + ")"
    sources = "; ".join(m.source for _, m in items.values())
    return _finalize(pd.concat(frames, ignore_index=True), vendor, sources, data_unit="kWh", default_unit="kWh")


# Load each file on its own so one bad file doesn't sink the batch, and so the user can
# pick which file to analyze instead of always getting everything merged together.
loaded: dict = {}
skipped: list[tuple[str, str]] = []
with st.spinner(T("spinner_load")):
    for f in uploaded:
        try:
            loaded[f.name] = _load_one(f.name, f.getvalue(), loader_unit)
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
st.caption(f"Unité appliquée aux données : **{getattr(meta, 'data_unit', 'kWh')}**")

# --------------------------------------------------------------------------- data quality
imp_tot, exp_tot = float(df.import_kWh.sum()), float(df.export_kWh.sum())
with st.expander(T("dq_expander"), expanded=len(loaded) > 1 or bool(skipped)):
    st.markdown(T("files_loaded_header"))
    for name, (d, m) in loaded.items():
        st.caption(T("file_ok", name=name, vendor=m.vendor, days=f"{m.coverage_days:.0f}",
                     imp=float(d.import_kWh.sum()), exp=float(d.export_kWh.sum()))
                   + f" | unité appliquée : {getattr(m, 'data_unit', 'kWh')}")
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
def _best_per_capacity_local(results: pd.DataFrame) -> pd.DataFrame:
    idx = results.groupby("Cap_kWh")["Gain_CHF"].idxmax()
    return results.loc[idx].sort_values("Cap_kWh").reset_index(drop=True)


def _auto_capacity_max_from_curve(
    results: pd.DataFrame,
    cap_limit: int,
    cap_step: int,
    min_gain_share: float = 0.98,
    marginal_floor_chf_per_kwh: float = 2.0,
    window_kwh: float = 10.0,
) -> int:
    """Choose an automatic upper bound once the gain curve has flattened.

    The returned value is a search limit, not necessarily the recommended capacity.
    A small margin is kept after the plateau so the charts still show why adding more
    capacity is not useful.
    """
    if results.empty:
        return int(cap_limit)

    f = _best_per_capacity_local(results).copy()
    f["Gain_mono"] = f["Gain_CHF"].cummax()
    gain_max = float(f["Gain_mono"].max())
    if gain_max <= 0:
        return int(max(f["Cap_kWh"].min(), 1))

    for i, row in f.iterrows():
        cap_i = float(row["Cap_kWh"])
        gain_i = float(row["Gain_mono"])
        if gain_i < gain_max * min_gain_share:
            continue

        future = f[f["Cap_kWh"] >= cap_i + window_kwh]
        if future.empty:
            continue
        j = int(future.index[0])
        cap_j = float(f.loc[j, "Cap_kWh"])
        gain_j = float(f.loc[j, "Gain_mono"])
        marginal = max(0.0, gain_j - gain_i) / max(cap_j - cap_i, 1e-9)

        if marginal <= marginal_floor_chf_per_kwh:
            margin = max(5, int(2 * cap_step))
            return int(min(cap_limit, round(cap_i + margin)))

    return int(cap_limit)


powers = list(range(int(p_min), int(p_max) + 1, int(p_step)))
cap_max_effective = int(cap_max)

if auto_cap_max:
    auto_limit = int(cap_max)
    auto_caps = list(range(int(cap_min), auto_limit + 1, int(cap_step)))
    if auto_caps and powers:
        with st.spinner("Recherche automatique de la capacité max..."):
            auto_results = grid_search(
                df.import_kWh.values,
                df.export_kWh.values,
                auto_caps,
                powers,
                meta.dt_hours,
                roundtrip_eff,
                tariff_import,
                tariff_export,
                meta.coverage_days,
                timestamps=df.timestamp.values,
                tariff_import_ht=tariff_import_ht,
                tariff_import_bt=tariff_import_bt,
                high_tariff_periods=high_tariff_periods,
                weekend_low_tariff=weekend_low_tariff,
            )
        cap_max_effective = _auto_capacity_max_from_curve(
            auto_results,
            cap_limit=auto_limit,
            cap_step=int(cap_step),
        )
        st.sidebar.caption(f"Cap. max auto utilisée : {cap_max_effective} kWh")

caps = list(range(int(cap_min), int(cap_max_effective) + 1, int(cap_step)))
if not caps or not powers:
    st.error(T("empty_range"))
    st.stop()

with st.spinner(T("spinner_sim", n=len(caps) * len(powers))):
    results = grid_search(
        df.import_kWh.values,
        df.export_kWh.values,
        caps,
        powers,
        meta.dt_hours,
        roundtrip_eff,
        tariff_import,
        tariff_export,
        meta.coverage_days,
        timestamps=df.timestamp.values,
        tariff_import_ht=tariff_import_ht,
        tariff_import_bt=tariff_import_bt,
        high_tariff_periods=high_tariff_periods,
        weekend_low_tariff=weekend_low_tariff,
    )
    rec = recommend(results, cycles_low=cycles_low, coverage_days=meta.coverage_days,
                    brand=brand)

best = rec.best
sim = simulate(
    df.import_kWh.values,
    df.export_kWh.values,
    best.Cap_kWh,
    best.Power_kW,
    meta.dt_hours,
    roundtrip_eff,
    tariff_import,
    tariff_export,
    meta.coverage_days,
    timestamps=df.timestamp.values,
    tariff_import_ht=tariff_import_ht,
    tariff_import_bt=tariff_import_bt,
    high_tariff_periods=high_tariff_periods,
    weekend_low_tariff=weekend_low_tariff,
)

# --------------------------------------------------------------------------- KPI cards
def _fmt_kwh(v: float) -> str:
    return f"{float(v):,.0f}".replace(",", " ")

def _fmt_chf(v: float) -> str:
    return f"{float(v):,.0f}".replace(",", " ")

import_before_total = float(sim.import_before)
import_after_total = float(sim.import_after_total)
import_avoided_total = float(sim.import_avoided)

export_before_total = float(sim.export_before)
export_after_total = float(sim.export_after_total)
export_avoided_total = float(sim.export_stored)

import_reduction_pct = (import_avoided_total / import_before_total * 100) if import_before_total > 0 else 0.0
export_reduction_pct = (export_avoided_total / export_before_total * 100) if export_before_total > 0 else 0.0

# Avec seulement import/export, on ne connaît pas toujours la production totale.
# On affiche donc l'augmentation d'autoconsommation comme surplus PV récupéré sur place.
autoconso_gain_pct = export_reduction_pct

big = rec.max_gain_pick
gain_share = (float(best.Gain_CHF) / float(rec.gain_max) * 100) if rec.gain_max > 0 else 0.0
gain_max_extra = float(rec.gain_max - best.Gain_CHF)

st.markdown('<div class="mar-summary-title">Résumé de la simulation</div>', unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="mar-card-grid-5">
        <div class="mar-card">
            <div class="mar-label"><span class="mar-icon">🔋</span>Capacité batterie</div>
            <div class="mar-value mar-blue">{best.Cap_kWh:.0f} kWh</div>
            <div class="mar-sub">Capacité proposée</div>
        </div>
        <div class="mar-card">
            <div class="mar-label"><span class="mar-icon">⚡</span>Puissance batterie</div>
            <div class="mar-value mar-blue">{best.Power_kW:.0f} kW</div>
            <div class="mar-sub">Puissance de charge/décharge</div>
        </div>
        <div class="mar-card">
            <div class="mar-label"><span class="mar-icon">💰</span>Économies annuelles</div>
            <div class="mar-value mar-green">{_fmt_chf(best.Gain_CHF)} CHF/an</div>
            <div class="mar-sub">Gain net HT/BT/revente</div>
        </div>
        <div class="mar-card">
            <div class="mar-label"><span class="mar-icon">♻️</span>Cycles équivalents</div>
            <div class="mar-value mar-purple">{best.Cycles_per_year:.0f}/an</div>
            <div class="mar-pill">{gain_share:.0f}% du gain maximal</div>
        </div>
        <div class="mar-card">
            <div class="mar-label"><span class="mar-icon">🟠</span>Surplus capté</div>
            <div class="mar-value mar-orange">{sim.surplus_captured:.0%}</div>
            <div class="mar-sub">du surplus solaire</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="mar-card-grid-6">
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">🔌</span>Import avant</div>
            <div class="mar-value small mar-blue">{_fmt_kwh(import_before_total)} kWh</div>
            <div class="mar-sub">Depuis le réseau</div>
        </div>
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">🏠</span>Import après</div>
            <div class="mar-value small mar-blue">{_fmt_kwh(import_after_total)} kWh</div>
            <div class="mar-sub">Depuis le réseau</div>
        </div>
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">⬇️</span>Import évité</div>
            <div class="mar-value small mar-green">{_fmt_kwh(import_avoided_total)} kWh</div>
            <div class="mar-sub">-{import_reduction_pct:.0f} %</div>
        </div>
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">🔆</span>Export avant</div>
            <div class="mar-value small mar-orange">{_fmt_kwh(export_before_total)} kWh</div>
            <div class="mar-sub">Vers le réseau</div>
        </div>
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">🏡</span>Export après</div>
            <div class="mar-value small mar-orange">{_fmt_kwh(export_after_total)} kWh</div>
            <div class="mar-sub">Vers le réseau</div>
        </div>
        <div class="mar-card small">
            <div class="mar-label"><span class="mar-icon">⬇️</span>Export évité</div>
            <div class="mar-value small mar-green">{_fmt_kwh(export_avoided_total)} kWh</div>
            <div class="mar-sub">-{export_reduction_pct:.0f} %</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="mar-autoconso">
        <div class="mar-label"><span class="mar-icon">☀️</span>Autoconsommation / valorisation du surplus solaire</div>
        <div class="mar-autoconso-grid">
            <div>
                <div class="mar-sub">Surplus initial</div>
                <div class="mar-value small mar-orange">{_fmt_kwh(export_before_total)} kWh</div>
            </div>
            <div class="mar-autoconso-cell">
                <div class="mar-sub">Surplus stocké par la batterie</div>
                <div class="mar-value small mar-green">{_fmt_kwh(export_avoided_total)} kWh</div>
            </div>
            <div class="mar-autoconso-cell">
                <div class="mar-sub">Augmentation d'autoconsommation</div>
                <div class="mar-value small mar-green">+{autoconso_gain_pct:.0f} %</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if gain_max_extra > 0:
    st.caption(
        f"Le gain maximum testé est de {_fmt_chf(rec.gain_max)} CHF/an avec "
        f"{big.Cap_kWh:.0f} kWh. La solution proposée atteint {gain_share:.0f}% de ce gain ; "
        f"aller au maximum n'ajoute que {_fmt_chf(gain_max_extra)} CHF/an."
    )

for code, params in rec.warnings:
    (st.error if code in ERROR_CODES else st.warning)(msg(L, code, params))
for code, params in rec.notes:
    st.caption("• " + msg(L, code, params))

with st.expander("Détail du gain tarifaire", expanded=False):
    tariff_detail = pd.DataFrame(
        {
            "Poste": [
                "Import évité haut tarif",
                "Import évité bas tarif",
                "Valeur de revente perdue",
                "Gain net batterie",
            ],
            "kWh/an": [
                getattr(sim, "import_avoided_ht", 0.0),
                getattr(sim, "import_avoided_bt", 0.0),
                getattr(sim, "export_stored", 0.0),
                "",
            ],
            "Tarif CHF/kWh": [
                tariff_import_ht,
                tariff_import_bt,
                tariff_export,
                "",
            ],
            "CHF/an": [
                getattr(sim, "gain_ht_chf", 0.0),
                getattr(sim, "gain_bt_chf", 0.0),
                -getattr(sim, "export_value_lost_chf", 0.0),
                getattr(sim, "gain_chf", 0.0),
            ],
        }
    )
    st.dataframe(tariff_detail, use_container_width=True, hide_index=True)
    st.caption(
        f"Formule : gain = import évité HT × {tariff_import_ht:.2f} "
        f"+ import évité BT × {tariff_import_bt:.2f} "
        f"- surplus stocké × {tariff_export:.2f}. "
        f"Profil utilisé : {tariff_profile}."
    )

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
    pay_caps = list(range(1, int(cap_max_effective) + 1))
    pay_gs = grid_search(
        df.import_kWh.values,
        df.export_kWh.values,
        pay_caps,
        powers,
        meta.dt_hours,
        roundtrip_eff,
        tariff_import,
        tariff_export,
        meta.coverage_days,
        timestamps=df.timestamp.values,
        tariff_import_ht=tariff_import_ht,
        tariff_import_bt=tariff_import_bt,
        high_tariff_periods=high_tariff_periods,
        weekend_low_tariff=weekend_low_tariff,
    )
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
    usable_cap = getattr(sim, "usable_capacity_kWh", best.Cap_kWh)
    soc_min = getattr(sim, "soc_min_pct", 0.0)
    soc_pct = soc_min + (sim.soc / usable_cap * (100.0 - soc_min)) if usable_cap > 0 else sim.soc * 0
    fig = go.Figure(go.Scatter(x=ts, y=soc_pct, mode="lines", line=dict(color="#7c3aed", width=1)))
    fig.update_layout(yaxis_title=T("axis_soc"), xaxis_title=T("axis_date"), height=420,
                      title=T("soc_title", cap=f"{best.Cap_kWh:.0f}", power=f"{best.Power_kW:.0f}"))
    st.plotly_chart(fig, use_container_width=True)

with tab_cyc:
    discharge = df.import_kWh.values - sim.import_after
    usable_cap = getattr(sim, "usable_capacity_kWh", best.Cap_kWh)
    cum_cycles = np.cumsum(discharge) / usable_cap if usable_cap > 0 else np.zeros_like(discharge)
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
st.divider()
if not pdf_sections:
    st.caption(T("pdf_sections_empty"))

pdf_bytes = generate_battery_report(
    df=df,
    meta=meta,
    rec=rec,
    best=best,
    big=big,
    sim=sim,
    brand=brand,
    tariff_profile=tariff_profile,
    tariff_import_ht=tariff_import_ht,
    tariff_import_bt=tariff_import_bt,
    tariff_export=tariff_export,
    gain_share=gain_share,
    gain_max_extra=gain_max_extra,
    cost_life=cost_life,
    sections=pdf_sections,
)

st.download_button(
    T("pdf_button"),
    pdf_bytes,
    file_name=T("pdf_filename"),
    mime="application/pdf",
)

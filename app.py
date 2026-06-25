# app.py
# Application Streamlit pour dimensionnement batterie PV
# Calcul des cycles corrigé : EFC = énergie réellement déchargée / capacité utile

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from recommend import optimize_battery


def build_cycle_comment(cycles: float, min_healthy: float = 150, max_healthy: float = 350) -> str:
    if cycles < min_healthy:
        return (
            f"Seulement {cycles:.0f} cycles équivalents/an : batterie peu sollicitée. "
            "Cela indique une capacité probablement trop élevée par rapport au surplus réellement disponible."
        )
    if cycles > max_healthy:
        return (
            f"{cycles:.0f} cycles équivalents/an : batterie fortement sollicitée. "
            "Le dimensionnement est énergétiquement actif, mais l'usure sera plus rapide."
        )
    return (
        f"{cycles:.0f} cycles équivalents/an : utilisation cohérente. "
        "La batterie est suffisamment utilisée sans être excessivement sollicitée."
    )


st.set_page_config(page_title="Dimensionnement Batterie", layout="wide")

st.title("Dimensionnement Batterie PV")
st.caption("Cycles calculés en cycles complets équivalents : énergie réellement déchargée / capacité utile.")


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(uploaded_file)

    if suffix == ".csv":
        try:
            return pd.read_csv(uploaded_file, sep=None, engine="python")
        except Exception:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, sep=";")

    raise ValueError("Format non supporté. Utilise un fichier .xlsx, .xls ou .csv.")


def find_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    normalized = {str(c).lower().strip(): c for c in df.columns}

    for key in keywords:
        key = key.lower()
        for low, original in normalized.items():
            if key in low:
                return original

    return None


def prepare_data(df: pd.DataFrame, date_col: str | None, import_col: str, export_col: str) -> pd.DataFrame:
    data = df.copy()

    if date_col and date_col != "Aucune":
        data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
        data = data.dropna(subset=[date_col]).set_index(date_col).sort_index()

    data[import_col] = pd.to_numeric(data[import_col], errors="coerce").fillna(0).clip(lower=0)
    data[export_col] = pd.to_numeric(data[export_col], errors="coerce").fillna(0).clip(lower=0)

    return data[[import_col, export_col]].rename(
        columns={
            import_col: "import",
            export_col: "export",
        }
    )


with st.sidebar:
    st.header("Données")

    uploaded = st.file_uploader("Fichier mesures", type=["xlsx", "xls", "csv"])

    st.header("Paramètres")

    unit = st.selectbox("Unité des valeurs import/export", ["kW", "kWh"], index=0)

    dt_hours = st.number_input(
        "Pas de temps (h)",
        min_value=0.01,
        max_value=24.0,
        value=0.25,
        step=0.25,
    )

    roundtrip_efficiency = st.number_input(
        "Rendement aller-retour",
        min_value=0.50,
        max_value=1.00,
        value=0.95,
        step=0.01,
    )

    soc_min_pct = st.number_input(
        "SOC minimum (%)",
        min_value=0.0,
        max_value=50.0,
        value=5.0,
        step=1.0,
    )

    st.header("Recherche")

    cap_min = st.number_input("Capacité min (kWh)", min_value=1.0, value=3.0, step=1.0)
    cap_max = st.number_input("Capacité max (kWh)", min_value=1.0, value=30.0, step=1.0)
    cap_step = st.number_input("Pas capacité (kWh)", min_value=0.5, value=1.0, step=0.5)

    pwr_min = st.number_input("Puissance min (kW)", min_value=1.0, value=1.0, step=1.0)
    pwr_max = st.number_input("Puissance max (kW)", min_value=1.0, value=10.0, step=1.0)
    pwr_step = st.number_input("Pas puissance (kW)", min_value=0.5, value=1.0, step=0.5)

    st.header("Tarifs")

    tariff_hp = st.number_input("Tarif import HP (CHF/kWh)", min_value=0.0, value=0.32, step=0.01)
    tariff_hc = st.number_input("Tarif import HC (CHF/kWh)", min_value=0.0, value=0.21, step=0.01)
    tariff_export = st.number_input("Tarif export (CHF/kWh)", min_value=0.0, value=0.08, step=0.01)

    weekend_full_low_tariff = st.checkbox("Week-end entièrement en HC", value=False)

    st.header("Recommandation")

    gain_threshold_pct = st.slider(
        "Seuil du gain maximum (%)",
        min_value=50,
        max_value=100,
        value=86,
        step=1,
    )

    min_healthy_cycles = st.number_input(
        "Seuil bas cycles sains",
        min_value=1,
        value=150,
        step=10,
    )

    max_healthy_cycles = st.number_input(
        "Seuil haut cycles sains",
        min_value=1,
        value=350,
        step=10,
    )


if uploaded is None:
    st.info("Charge un fichier Excel ou CSV contenant au minimum une colonne import et une colonne export.")
    st.stop()


try:
    raw = read_uploaded_file(uploaded)
except Exception as e:
    st.error(f"Lecture impossible : {e}")
    st.stop()


if raw.empty:
    st.error("Le fichier est vide.")
    st.stop()


st.subheader("Colonnes détectées")

candidate_date = find_column(raw, ["date", "datetime", "horodatage", "temps"])
candidate_import = find_column(raw, ["import", "achat", "energie active", "énergie active", "conso", "consommation"])
candidate_export = find_column(raw, ["export", "revente", "refoul", "injection", "surplus"])

cols = ["Aucune"] + list(raw.columns)

c1, c2, c3 = st.columns(3)

with c1:
    date_col = st.selectbox(
        "Colonne date/heure",
        cols,
        index=cols.index(candidate_date) if candidate_date in cols else 0,
    )

with c2:
    import_col = st.selectbox(
        "Colonne import / achat",
        list(raw.columns),
        index=list(raw.columns).index(candidate_import) if candidate_import in raw.columns else 0,
    )

with c3:
    export_col = st.selectbox(
        "Colonne export / revente",
        list(raw.columns),
        index=list(raw.columns).index(candidate_export) if candidate_export in raw.columns else min(1, len(raw.columns) - 1),
    )


data = prepare_data(raw, date_col, import_col, export_col)


capacities = []
x = cap_min
while x <= cap_max + 1e-9:
    capacities.append(round(x, 3))
    x += cap_step


powers = []
p = pwr_min
while p <= pwr_max + 1e-9:
    powers.append(round(p, 3))
    p += pwr_step


recommended, gain_max, table = optimize_battery(
    import_kw_or_kwh=data["import"],
    export_kw_or_kwh=data["export"],
    capacities_kwh=capacities,
    powers_kw=powers,
    dt_hours=dt_hours,
    unit=unit,
    roundtrip_efficiency=roundtrip_efficiency,
    soc_min_pct=soc_min_pct,
    tariff_import_hp=tariff_hp,
    tariff_import_hc=tariff_hc,
    tariff_export=tariff_export,
    weekend_full_low_tariff=weekend_full_low_tariff,
    gain_threshold_pct=gain_threshold_pct,
    min_healthy_cycles=min_healthy_cycles,
    max_healthy_cycles=max_healthy_cycles,
)


st.subheader("Batterie recommandée")

m1, m2, m3, m4 = st.columns(4)

m1.metric("Capacité", f"{recommended.capacity_kwh:.1f} kWh")
m2.metric("Puissance", f"{recommended.power_kw:.1f} kW")
m3.metric("Économies", f"{recommended.gain_chf:.0f} CHF/an")
m4.metric("Cycles EFC", f"{recommended.cycles_efc_per_year:.0f} /an")

st.write(
    build_cycle_comment(
        recommended.cycles_efc_per_year,
        min_healthy_cycles,
        max_healthy_cycles,
    )
)

st.markdown(
    f"""
**Méthode cycles utilisée :**

Cycles = énergie réellement déchargée / capacité utile

- Énergie réellement déchargée : **{recommended.energy_discharged_kwh:,.0f} kWh/an**
- Capacité nominale : **{recommended.capacity_kwh:.1f} kWh**
- SOC minimum : **{soc_min_pct:.0f} %**
- Capacité utile : **{recommended.usable_capacity_kwh:.2f} kWh**
- Cycles équivalents : **{recommended.cycles_efc_per_year:.1f} cycles/an**
"""
)


st.subheader("Résultats annuels")

summary = pd.DataFrame(
    {
        "Indicateur": [
            "Import avant",
            "Import après",
            "Export avant",
            "Export après",
            "Import évité",
            "Surplus capté",
            "Énergie chargée batterie",
            "Énergie déchargée batterie",
            "SOC min réel",
            "SOC max réel",
            "Cycles/jour",
        ],
        "Valeur": [
            f"{recommended.import_before_kwh:,.0f} kWh",
            f"{recommended.import_after_kwh:,.0f} kWh",
            f"{recommended.export_before_kwh:,.0f} kWh",
            f"{recommended.export_after_kwh:,.0f} kWh",
            f"{recommended.import_avoided_kwh:,.0f} kWh",
            f"{recommended.export_avoided_kwh:,.0f} kWh",
            f"{recommended.energy_charged_kwh:,.0f} kWh",
            f"{recommended.energy_discharged_kwh:,.0f} kWh",
            f"{recommended.soc_min_real_pct:.1f} %",
            f"{recommended.soc_max_real_pct:.1f} %",
            f"{recommended.cycles_per_day:.2f}",
        ],
    }
)

st.dataframe(summary, use_container_width=True, hide_index=True)


st.subheader("Comparaison avec le gain maximum")

st.write(
    f"Gain maximum trouvé : **{gain_max.capacity_kwh:.1f} kWh / {gain_max.power_kw:.1f} kW**, "
    f"**{gain_max.gain_chf:.0f} CHF/an**, "
    f"**{gain_max.cycles_efc_per_year:.0f} cycles/an**."
)


st.subheader("Graphiques")

best_by_capacity = (
    table.sort_values(["capacity_kwh", "gain_chf"], ascending=[True, False])
    .groupby("capacity_kwh", as_index=False)
    .first()
)

fig1, ax1 = plt.subplots()
ax1.plot(best_by_capacity["capacity_kwh"], best_by_capacity["gain_chf"], marker="o")
ax1.axvline(recommended.capacity_kwh, linestyle="--")
ax1.set_xlabel("Capacité batterie (kWh)")
ax1.set_ylabel("Gain annuel (CHF/an)")
ax1.set_title("Gain annuel selon la capacité")
st.pyplot(fig1)

fig2, ax2 = plt.subplots()
ax2.plot(best_by_capacity["capacity_kwh"], best_by_capacity["cycles_efc_per_year"], marker="o")
ax2.axhline(min_healthy_cycles, linestyle="--")
ax2.axhline(max_healthy_cycles, linestyle="--")
ax2.axvline(recommended.capacity_kwh, linestyle="--")
ax2.set_xlabel("Capacité batterie (kWh)")
ax2.set_ylabel("Cycles équivalents/an")
ax2.set_title("Cycles EFC selon la capacité")
st.pyplot(fig2)

fig3, ax3 = plt.subplots()
recommended.soc_series_pct.plot(ax=ax3)
ax3.set_xlabel("Date")
ax3.set_ylabel("SOC (%)")
ax3.set_title(f"État de charge - {recommended.capacity_kwh:.1f} kWh / {recommended.power_kw:.1f} kW")
st.pyplot(fig3)


st.subheader("Détail par capacité / puissance")

st.dataframe(
    table[
        [
            "capacity_kwh",
            "power_kw",
            "gain_chf",
            "cycles_efc_per_year",
            "cycles_per_day",
            "import_avoided_kwh",
            "export_avoided_kwh",
            "energy_discharged_kwh",
            "usable_capacity_kwh",
            "status_cycles",
        ]
    ].round(2),
    use_container_width=True,
    hide_index=True,
)


csv = table.to_csv(index=False).encode("utf-8-sig")

st.download_button(
    "Télécharger le détail CSV",
    data=csv,
    file_name="detail_dimensionnement_batterie.csv",
    mime="text/csv",
)

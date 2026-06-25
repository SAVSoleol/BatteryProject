# recommend.py
# Dimensionnement batterie PV avec calcul correct des cycles équivalents (EFC)
# Méthode retenue :
# EFC = énergie réellement déchargée par la batterie / capacité utile
# capacité utile = capacité nominale x (1 - SOC_min)

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class BatterySimulationResult:
    capacity_kwh: float
    power_kw: float
    gain_chf: float
    import_before_kwh: float
    import_after_kwh: float
    export_before_kwh: float
    export_after_kwh: float
    import_avoided_kwh: float
    export_avoided_kwh: float
    energy_charged_kwh: float
    energy_discharged_kwh: float
    usable_capacity_kwh: float
    cycles_efc_per_year: float
    cycles_per_day: float
    usage_ratio_per_day: float
    soc_min_real_pct: float
    soc_max_real_pct: float
    soc_series_pct: pd.Series
    monthly: pd.DataFrame


def _as_series(values, index=None, name: str = "") -> pd.Series:
    if isinstance(values, pd.Series):
        s = values.copy()
        if name:
            s.name = name
        return s
    return pd.Series(values, index=index, name=name)


def _prepare_profiles(
    import_kw_or_kwh,
    export_kw_or_kwh,
    dt_hours: float,
    unit: str = "kW",
) -> tuple[pd.Series, pd.Series]:
    """
    Retourne import/export en kWh par pas de temps.

    unit="kW"  : les valeurs sont des puissances moyennes, conversion kW x dt
    unit="kWh" : les valeurs sont déjà des énergies par pas
    """
    imp = _as_series(import_kw_or_kwh, name="import")
    exp = _as_series(export_kw_or_kwh, index=imp.index, name="export")

    imp = pd.to_numeric(imp, errors="coerce").fillna(0).clip(lower=0)
    exp = pd.to_numeric(exp, errors="coerce").fillna(0).clip(lower=0)

    if unit.lower() == "kw":
        imp = imp * dt_hours
        exp = exp * dt_hours
    elif unit.lower() == "kwh":
        pass
    else:
        raise ValueError("unit doit être 'kW' ou 'kWh'.")

    return imp, exp


def _is_high_tariff(ts, hp_ranges=((7, 12), (17, 23)), weekend_full_low_tariff=False) -> bool:
    if weekend_full_low_tariff and ts.weekday() >= 5:
        return False

    hour = ts.hour + ts.minute / 60
    for start, end in hp_ranges:
        if start <= hour < end:
            return True
    return False


def _tariff_series(index, hp_price: float, hc_price: float, hp_ranges, weekend_full_low_tariff: bool):
    if isinstance(index, pd.DatetimeIndex):
        return pd.Series(
            [
                hp_price if _is_high_tariff(ts, hp_ranges, weekend_full_low_tariff) else hc_price
                for ts in index
            ],
            index=index,
            name="tarif_import",
        )
    return pd.Series(hp_price, index=index, name="tarif_import")


def simulate_battery(
    import_kw_or_kwh,
    export_kw_or_kwh,
    capacity_kwh: float,
    power_kw: float,
    dt_hours: float = 0.25,
    unit: str = "kW",
    roundtrip_efficiency: float = 0.95,
    soc_min_pct: float = 5.0,
    tariff_import_hp: float = 0.32,
    tariff_import_hc: float = 0.21,
    tariff_export: float = 0.08,
    hp_ranges=((7, 12), (17, 23)),
    weekend_full_low_tariff: bool = False,
) -> BatterySimulationResult:
    """
    Simulation autoconsommation batterie.

    Priorité :
    - charge sur surplus PV/export
    - décharge pour couvrir l'import réseau
    - pas de charge réseau artificielle
    """

    if capacity_kwh <= 0:
        raise ValueError("capacity_kwh doit être > 0.")
    if power_kw <= 0:
        raise ValueError("power_kw doit être > 0.")

    imp, exp = _prepare_profiles(import_kw_or_kwh, export_kw_or_kwh, dt_hours, unit)
    index = imp.index

    eta = float(roundtrip_efficiency)
    if not 0 < eta <= 1:
        raise ValueError("roundtrip_efficiency doit être entre 0 et 1.")

    # Répartition simple des pertes : rendement côté charge et côté décharge.
    eta_charge = np.sqrt(eta)
    eta_discharge = np.sqrt(eta)

    usable_capacity_kwh = capacity_kwh * (1 - soc_min_pct / 100)
    soc_kwh = 0.0  # énergie utilisable au-dessus du SOC min

    max_power_energy = power_kw * dt_hours

    import_after = []
    export_after = []
    soc_values = []
    charged_from_pv = []
    discharged_to_load = []

    for imp_kwh, exp_kwh in zip(imp.to_numpy(), exp.to_numpy()):
        # 1) charge avec surplus exportable
        charge_input_kwh = min(exp_kwh, max_power_energy, (usable_capacity_kwh - soc_kwh) / eta_charge)
        stored_kwh = charge_input_kwh * eta_charge
        soc_kwh += stored_kwh
        exp_remaining = exp_kwh - charge_input_kwh

        # 2) décharge pour éviter import
        discharge_output_kwh = min(imp_kwh, max_power_energy, soc_kwh * eta_discharge)
        removed_from_battery_kwh = discharge_output_kwh / eta_discharge
        soc_kwh -= removed_from_battery_kwh
        imp_remaining = imp_kwh - discharge_output_kwh

        import_after.append(imp_remaining)
        export_after.append(exp_remaining)
        charged_from_pv.append(charge_input_kwh)
        discharged_to_load.append(discharge_output_kwh)

        soc_pct = soc_min_pct + (soc_kwh / usable_capacity_kwh * (100 - soc_min_pct) if usable_capacity_kwh > 0 else 0)
        soc_values.append(soc_pct)

    import_after = pd.Series(import_after, index=index, name="import_after_kwh")
    export_after = pd.Series(export_after, index=index, name="export_after_kwh")
    charged_from_pv = pd.Series(charged_from_pv, index=index, name="energy_charged_kwh")
    discharged_to_load = pd.Series(discharged_to_load, index=index, name="energy_discharged_kwh")
    soc_series_pct = pd.Series(soc_values, index=index, name="soc_pct")

    import_price = _tariff_series(index, tariff_import_hp, tariff_import_hc, hp_ranges, weekend_full_low_tariff)

    cost_before = (imp * import_price).sum() - (exp * tariff_export).sum()
    cost_after = (import_after * import_price).sum() - (export_after * tariff_export).sum()
    gain_chf = float(cost_before - cost_after)

    import_before_kwh = float(imp.sum())
    import_after_kwh = float(import_after.sum())
    export_before_kwh = float(exp.sum())
    export_after_kwh = float(export_after.sum())

    import_avoided_kwh = import_before_kwh - import_after_kwh
    export_avoided_kwh = export_before_kwh - export_after_kwh

    energy_charged_kwh = float(charged_from_pv.sum())
    energy_discharged_kwh = float(discharged_to_load.sum())

    # Méthode correcte : cycles complets équivalents, basés sur l'énergie réellement déchargée
    cycles_efc = energy_discharged_kwh / usable_capacity_kwh if usable_capacity_kwh > 0 else 0

    if isinstance(index, pd.DatetimeIndex) and len(index) > 0:
        days = max((index.max() - index.min()).total_seconds() / 86400, 1)
    else:
        days = max(len(imp) * dt_hours / 24, 1)

    cycles_per_day = cycles_efc / days
    usage_ratio_per_day = cycles_per_day  # 1.0 = une capacité utile complète utilisée par jour

    monthly = pd.DataFrame(
        {
            "import_avant_kwh": imp,
            "import_apres_kwh": import_after,
            "export_avant_kwh": exp,
            "export_apres_kwh": export_after,
            "charge_batterie_kwh": charged_from_pv,
            "decharge_batterie_kwh": discharged_to_load,
        }
    )

    if isinstance(monthly.index, pd.DatetimeIndex):
        monthly = monthly.resample("ME").sum()
        monthly.index = monthly.index.strftime("%Y-%m")
    else:
        monthly = pd.DataFrame(monthly.sum()).T

    return BatterySimulationResult(
        capacity_kwh=float(capacity_kwh),
        power_kw=float(power_kw),
        gain_chf=gain_chf,
        import_before_kwh=import_before_kwh,
        import_after_kwh=import_after_kwh,
        export_before_kwh=export_before_kwh,
        export_after_kwh=export_after_kwh,
        import_avoided_kwh=float(import_avoided_kwh),
        export_avoided_kwh=float(export_avoided_kwh),
        energy_charged_kwh=energy_charged_kwh,
        energy_discharged_kwh=energy_discharged_kwh,
        usable_capacity_kwh=float(usable_capacity_kwh),
        cycles_efc_per_year=float(cycles_efc),
        cycles_per_day=float(cycles_per_day),
        usage_ratio_per_day=float(usage_ratio_per_day),
        soc_min_real_pct=float(soc_series_pct.min()) if len(soc_series_pct) else soc_min_pct,
        soc_max_real_pct=float(soc_series_pct.max()) if len(soc_series_pct) else soc_min_pct,
        soc_series_pct=soc_series_pct,
        monthly=monthly,
    )


def optimize_battery(
    import_kw_or_kwh,
    export_kw_or_kwh,
    capacities_kwh: Iterable[float],
    powers_kw: Iterable[float],
    dt_hours: float = 0.25,
    unit: str = "kW",
    roundtrip_efficiency: float = 0.95,
    soc_min_pct: float = 5.0,
    tariff_import_hp: float = 0.32,
    tariff_import_hc: float = 0.21,
    tariff_export: float = 0.08,
    hp_ranges=((7, 12), (17, 23)),
    weekend_full_low_tariff: bool = False,
    min_healthy_cycles: float = 150,
    max_healthy_cycles: float = 350,
    gain_threshold_pct: float = 86,
) -> tuple[BatterySimulationResult, BatterySimulationResult, pd.DataFrame]:
    """
    Retourne :
    - recommandation principale
    - variante gain maximum
    - tableau de toutes les simulations

    Logique recommandée :
    1) calculer toutes les combinaisons capacité/puissance
    2) identifier le gain maximum
    3) retenir la plus petite capacité qui atteint gain_threshold_pct du gain max,
       puis la puissance la plus faible suffisante pour ce gain.
    4) les cycles EFC sont informatifs et servent à alerter le surdimensionnement.
    """

    results: list[BatterySimulationResult] = []

    for cap in capacities_kwh:
        for pwr in powers_kw:
            results.append(
                simulate_battery(
                    import_kw_or_kwh=import_kw_or_kwh,
                    export_kw_or_kwh=export_kw_or_kwh,
                    capacity_kwh=float(cap),
                    power_kw=float(pwr),
                    dt_hours=dt_hours,
                    unit=unit,
                    roundtrip_efficiency=roundtrip_efficiency,
                    soc_min_pct=soc_min_pct,
                    tariff_import_hp=tariff_import_hp,
                    tariff_import_hc=tariff_import_hc,
                    tariff_export=tariff_export,
                    hp_ranges=hp_ranges,
                    weekend_full_low_tariff=weekend_full_low_tariff,
                )
            )

    rows = []
    for r in results:
        rows.append(
            {
                "capacity_kwh": r.capacity_kwh,
                "power_kw": r.power_kw,
                "gain_chf": r.gain_chf,
                "cycles_efc_per_year": r.cycles_efc_per_year,
                "cycles_per_day": r.cycles_per_day,
                "usage_ratio_per_day": r.usage_ratio_per_day,
                "import_avoided_kwh": r.import_avoided_kwh,
                "export_avoided_kwh": r.export_avoided_kwh,
                "energy_charged_kwh": r.energy_charged_kwh,
                "energy_discharged_kwh": r.energy_discharged_kwh,
                "usable_capacity_kwh": r.usable_capacity_kwh,
                "soc_max_real_pct": r.soc_max_real_pct,
            }
        )

    table = pd.DataFrame(rows).sort_values(["capacity_kwh", "power_kw"]).reset_index(drop=True)

    idx_gain_max = table["gain_chf"].idxmax()
    gain_max_row = table.loc[idx_gain_max]
    gain_max = gain_max_row["gain_chf"]

    eligible = table[table["gain_chf"] >= gain_max * gain_threshold_pct / 100].copy()

    # Recommandation : atteindre l'essentiel du gain avec le moins de capacité possible,
    # puis la puissance la plus basse dans cette capacité.
    eligible = eligible.sort_values(["capacity_kwh", "power_kw", "gain_chf"], ascending=[True, True, False])
    rec_row = eligible.iloc[0]

    def find_result(row) -> BatterySimulationResult:
        for r in results:
            if r.capacity_kwh == float(row["capacity_kwh"]) and r.power_kw == float(row["power_kw"]):
                return r
        raise RuntimeError("Résultat introuvable.")

    recommended = find_result(rec_row)
    max_gain_result = find_result(gain_max_row)

    table["status_cycles"] = np.select(
        [
            table["cycles_efc_per_year"] < min_healthy_cycles,
            table["cycles_efc_per_year"] > max_healthy_cycles,
        ],
        [
            "surdimensionnée / peu cyclée",
            "fortement sollicitée",
        ],
        default="zone saine",
    )

    return recommended, max_gain_result, table


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

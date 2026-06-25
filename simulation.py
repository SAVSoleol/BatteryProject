"""Battery dispatch simulation + (cap, power) grid search.

ONE simulation function, replacing the three duplicated loops in the old app.

Dispatch model (greedy self-consumption, standard for behind-the-meter sizing):
  per interval, charge the battery from any solar surplus, then discharge it to cover
  any grid import, respecting capacity, power, and round-trip efficiency.

Efficiency convention (consistent, not double-counted):
  eta = sqrt(roundtrip_eff). Charging stores `charge*eta` in the cells; delivering
  `discharge` to the load draws `discharge/eta` from the cells. Round trip = eta*eta.

Cycle definition:
  equivalent_full_cycles = (total energy discharged to load) / (usable capacity).
  usable capacity = nameplate capacity x (1 - SOC_min).
  Annualized to /year using the data's coverage (with a warning if < ~360 days).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Optional numba acceleration; falls back to pure Python (slower but identical results).
try:
    from numba import njit

    HAS_NUMBA = True
except Exception:  # pragma: no cover - numba is optional
    HAS_NUMBA = False

    def njit(*args, **kwargs):
        def _wrap(fn):
            return fn

        return _wrap(args[0]) if args and callable(args[0]) else _wrap


@njit(cache=True)
def _dispatch(imp, exp, capacity, power_per_step, eta):
    """Tight inner loop. Returns (imp_after, exp_after, soc, charge_tot, discharge_tot)."""
    n = imp.shape[0]
    imp_after = np.empty(n)
    exp_after = np.empty(n)
    soc = np.empty(n)
    soc_val = 0.0
    charge_tot = 0.0
    discharge_tot = 0.0

    for i in range(n):
        # --- charge from surplus ---
        charge_i = exp[i]
        if charge_i > power_per_step:
            charge_i = power_per_step
        max_charge = (capacity - soc_val) / eta  # keep stored energy <= capacity
        if charge_i > max_charge:
            charge_i = max_charge
        if charge_i < 0.0:
            charge_i = 0.0
        soc_val += charge_i * eta
        exp_after[i] = exp[i] - charge_i
        charge_tot += charge_i

        # --- discharge to load ---
        discharge_i = imp[i]
        if discharge_i > power_per_step:
            discharge_i = power_per_step
        max_discharge = soc_val * eta  # can't pull below empty
        if discharge_i > max_discharge:
            discharge_i = max_discharge
        if discharge_i < 0.0:
            discharge_i = 0.0
        soc_val -= discharge_i / eta
        imp_after[i] = imp[i] - discharge_i
        discharge_tot += discharge_i

        soc[i] = soc_val

    return imp_after, exp_after, soc, charge_tot, discharge_tot


@dataclass
class SimResult:
    capacity_kWh: float
    power_kW: float
    soc: np.ndarray            # state of charge per interval (kWh)
    import_after: np.ndarray   # grid import after battery (kWh per interval)
    export_after: np.ndarray   # grid export after battery (kWh per interval)
    import_before: float
    export_before: float
    import_avoided: float      # = energy discharged to load
    export_stored: float       # = energy taken from surplus to charge
    gain_chf: float            # annual financial benefit
    cycles_per_year: float
    usable_capacity_kWh: float
    soc_min_pct: float
    charge_total_kWh: float
    discharge_total_kWh: float
    surplus_captured: float    # fraction of solar surplus the battery soaks up (0..1)
    import_reduction: float    # fraction of grid import avoided (0..1)

    @property
    def import_after_total(self) -> float:
        return float(self.import_after.sum())

    @property
    def export_after_total(self) -> float:
        return float(self.export_after.sum())


def simulate(
    import_kWh: np.ndarray,
    export_kWh: np.ndarray,
    capacity_kWh: float,
    power_kW: float,
    dt_hours: float,
    roundtrip_eff: float,
    tariff_import: float,
    tariff_export: float,
    coverage_days: float | None = None,
    soc_min_pct: float = 5.0,
) -> SimResult:
    """Run one battery simulation and return energy + financial + cycle metrics."""
    imp = np.ascontiguousarray(import_kWh, dtype=np.float64)
    exp = np.ascontiguousarray(export_kWh, dtype=np.float64)
    eta = float(np.sqrt(roundtrip_eff))
    power_per_step = power_kW * dt_hours

    usable_capacity_kWh = float(capacity_kWh) * (1.0 - float(soc_min_pct) / 100.0)
    usable_capacity_kWh = max(usable_capacity_kWh, 0.0)

    imp_after, exp_after, soc, charge_tot, discharge_tot = _dispatch(
        imp, exp, usable_capacity_kWh, power_per_step, eta
    )

    import_before = float(imp.sum())
    export_before = float(exp.sum())
    import_avoided = float(discharge_tot)
    export_stored = float(charge_tot)
    gain = import_avoided * tariff_import - export_stored * tariff_export

    # Annualize cycles to /year from however much data we have.
    days = coverage_days if coverage_days and coverage_days > 0 else len(imp) * dt_hours / 24.0
    cycles_total = discharge_tot / usable_capacity_kWh if usable_capacity_kWh > 0 else 0.0
    cycles_per_year = cycles_total * 365.0 / days if days > 0 else 0.0

    # Honest, meter-computable shares (we only see surplus/export, not total PV).
    surplus_captured = (export_stored / export_before) if export_before > 0 else 0.0
    import_reduction = (import_avoided / import_before) if import_before > 0 else 0.0

    return SimResult(
        capacity_kWh=float(capacity_kWh),
        power_kW=float(power_kW),
        soc=soc,
        import_after=imp_after,
        export_after=exp_after,
        import_before=import_before,
        export_before=export_before,
        import_avoided=import_avoided,
        export_stored=export_stored,
        gain_chf=float(gain),
        cycles_per_year=float(cycles_per_year),
        usable_capacity_kWh=float(usable_capacity_kWh),
        soc_min_pct=float(soc_min_pct),
        charge_total_kWh=float(charge_tot),
        discharge_total_kWh=float(discharge_tot),
        surplus_captured=float(surplus_captured),
        import_reduction=float(import_reduction),
    )


def grid_search(
    import_kWh: np.ndarray,
    export_kWh: np.ndarray,
    caps,
    powers,
    dt_hours: float,
    roundtrip_eff: float,
    tariff_import: float,
    tariff_export: float,
    coverage_days: float | None = None,
    soc_min_pct: float = 5.0,
) -> pd.DataFrame:
    """Simulate every (capacity, power) pair. Returns a tidy results table."""
    imp = np.ascontiguousarray(import_kWh, dtype=np.float64)
    exp = np.ascontiguousarray(export_kWh, dtype=np.float64)
    eta = float(np.sqrt(roundtrip_eff))

    days = coverage_days if coverage_days and coverage_days > 0 else len(imp) * dt_hours / 24.0
    rows = []
    for cap in caps:
        for p in powers:
            usable_cap = float(cap) * (1.0 - float(soc_min_pct) / 100.0)
            usable_cap = max(usable_cap, 0.0)

            _, _, _, charge_tot, discharge_tot = _dispatch(imp, exp, usable_cap, p * dt_hours, eta)
            gain = discharge_tot * tariff_import - charge_tot * tariff_export
            cycles_year = (discharge_tot / usable_cap * 365.0 / days) if (usable_cap > 0 and days > 0) else 0.0
            rows.append(
                {
                    "Cap_kWh": float(cap),
                    "Power_kW": float(p),
                    "Gain_CHF": float(gain),
                    "Cycles_per_year": float(cycles_year),
                    "Import_avoided_kWh": float(discharge_tot),
                    "Export_stored_kWh": float(charge_tot),
                    "Usable_capacity_kWh": float(usable_cap),
                    "SOC_min_pct": float(soc_min_pct),
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    # Quick smoke test on the Ross Nicolas full-year file.
    # Resolve data folder relative to this script, falling back to CWD.
    from pathlib import Path
    from loaders import load_meter_file

    script_dir = Path(__file__).resolve().parent
    sample = next(
        (p for p in [
            script_dir / "data" / "battery_data" / "Groupe E - Ross Nicolas - Mesures 01.01.25 - 31.12.25.xlsx",
            Path("data/battery_data/Groupe E - Ross Nicolas - Mesures 01.01.25 - 31.12.25.xlsx"),
        ] if p.is_file()),
        None,
    )
    if sample is None:
        raise SystemExit("Sample file not found. Place it under data/battery_data/ next to this script, or pass it explicitly.")
    df, meta = load_meter_file(sample)
    print(f"Loaded {meta.vendor}: {meta.n_rows} rows, {meta.coverage_days} days, dt={meta.dt_hours}")
    print(f"numba acceleration: {HAS_NUMBA}")

    res = simulate(
        df.import_kWh.values, df.export_kWh.values,
        capacity_kWh=10, power_kW=5, dt_hours=meta.dt_hours,
        roundtrip_eff=0.92, tariff_import=0.32, tariff_export=0.08,
        coverage_days=meta.coverage_days,
    )
    print(f"\n10 kWh / 5 kW battery:")
    print(f"  gain         = {res.gain_chf:8.0f} CHF/yr")
    print(f"  cycles       = {res.cycles_per_year:8.1f} /yr")
    print(f"  import avoided = {res.import_avoided:8.0f} kWh  (was {res.import_before:.0f})")
    print(f"  export stored  = {res.export_stored:8.0f} kWh  (was {res.export_before:.0f})")

    gs = grid_search(
        df.import_kWh.values, df.export_kWh.values,
        caps=range(5, 21, 1), powers=range(3, 11, 1), dt_hours=meta.dt_hours,
        roundtrip_eff=0.92, tariff_import=0.32, tariff_export=0.08,
        coverage_days=meta.coverage_days,
    )
    print(f"\nGrid search: {len(gs)} combos")
    print(gs.sort_values("Gain_CHF", ascending=False).head(5).to_string(index=False))

"""Cycles-aware battery recommendation.

The client's complaint: the old "biggest gain" pick is often OVERSIZED. The gain-vs-capacity
curve is concave, so a fixed "95% of max gain" floor always lands on a big, under-cycled
battery. Fix: make CYCLES the primary constraint (anti-oversizing), then maximize value
within it.

Logic:
  Stage 1 (utilization floor): keep candidates with cycles/year >= cycles_low (healthy use).
  Stage 2 (value):             among those, pick the highest-gain one, i.e. the LARGEST
                               battery that is still well used. Tie-break to the smallest
                               power. Falls back to the highest-cycle candidate (and warns)
                               if surplus is too low for anything to reach the floor.

Healthy band from research (PROJECT_NOTES.md §6): ~250-300 cycles/yr. The target is
anchored on the *installed battery brand's* own warranty (see BRANDS below): the GoodWe
Lynx D (GW8.3-BAT, the installer's actual hardware and the default) is calendar-limited,
not cycle-limited, its ~10,000-cycle cell life dwarfs any realistic solar cycling, while
Huawei LUNA2000 (which here is only the meter / data source) is designed around ~263/yr.
The selected brand sets the healthy band, the oversized flag, and the warranty sources
shown in the UI; below ~150/yr is flagged oversized regardless.
`gain_threshold` is kept only to report the old "smallest within X% of max gain" pick for
comparison, it no longer drives the recommendation.

`warnings` and `notes` are language-neutral: each is a (code, params) tuple. The UI layer
(see i18n.MSG / i18n.msg) renders them in the chosen language, so this module stays free of
display text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

Msg = tuple[str, dict]  # (message code, format params), rendered by i18n.msg()

# Generic LFP sizing band, kept as the fallback / GoodWe default.
CYCLES_HEALTHY_LOW = 250.0
CYCLES_HEALTHY_HIGH = 300.0
CYCLES_OVERSIZED_BELOW = 150.0


@dataclass(frozen=True)
class BrandSpec:
    """A battery brand's cycle target plus the sources it's anchored on.

    cycles_low / cycles_high : the healthy sizing band (green band on the chart; the low
                               end is also the default anti-oversizing floor).
    oversized_below          : below this cycles/yr, flag the battery as oversized.
    design_cycles_yr         : the manufacturer's own warranty design point (cycles/yr),
                               shown for context, not a hard limit.
    sources                  : (label, url) pairs surfaced in the UI so the figures are
                               auditable by the installer / client.

    The prose note explaining the warranty lives in i18n (TR["brand_note_<key>"]) so it
    can be shown in the chosen language, this module stays free of display text.
    """

    key: str
    name: str
    cycles_low: float
    cycles_high: float
    oversized_below: float
    design_cycles_yr: float
    sources: tuple[tuple[str, str], ...]


# GoodWe is the installer's actual hardware -> the default anchor. Confirmed model:
# Lynx D (HV) GW8.3-BAT-D-G20 (8.32 kWh rated / 8.0 kWh usable LFP module); the client's
# install is 4 modules = 32 kWh. Its cell life (~10,000 full cycles) far exceeds the
# 10-yr calendar warranty, so it is calendar-limited, not cycle-limited -> a generous
# healthy ceiling (the "verify against warranted throughput" nudge rarely needs to fire).
GOODWE = BrandSpec(
    key="goodwe",
    name="GoodWe Lynx D (GW8.3-BAT)",
    cycles_low=250.0,
    cycles_high=350.0,
    oversized_below=150.0,
    design_cycles_yr=1000.0,  # 10,000-cycle cell life / 10-yr warranty (calendar-limited)
    sources=(
        ("GoodWe Lynx D Series (HV), product page",
         "https://en.goodwe.com/lynxd"),
        ("GoodWe battery compatibility overview (GW8.3-BAT-D module), PDF",
         "https://en.goodwe.com/Ftp/EN/Downloads/User%20Manual/GW_Battery%20Compatibility%20Overview-EN.pdf"),
        ("GW8.3-BAT-D-G20 spec & ~10,000-cycle life (reseller listing)",
         "https://www.solarproof.com.au/products/GW83-BAT-D-G20/"),
        ("GoodWe battery review, Solar Choice (independent)",
         "https://www.solarchoice.net.au/products/batteries/goodwe-review/"),
    ),
)

# Huawei is the meter / data source here (FusionSolar exports), not necessarily the battery.
# Kept selectable for sites that do run LUNA2000 hardware.
HUAWEI = BrandSpec(
    key="huawei",
    name="Huawei (LUNA2000)",
    cycles_low=250.0,
    cycles_high=300.0,
    oversized_below=150.0,
    design_cycles_yr=263.0,
    sources=(
        ("Huawei LUNA2000-7/14/21-S1, spec & warranty",
         "https://solar.huawei.com/en/products/LUNA2000-7-14-21-S1/specs/"),
        ("Huawei FusionSolar EU warranty conditions, SKE Solar",
         "https://ske-solar.com/en/support/warranty/huawei-fusionsolar-warranty-conditions/"),
        ("LUNA2000 battery system specifications, Huawei support",
         "https://support.huawei.com/enterprise/en/doc/EDOC1100186676/661b0e12/luna2000-battery-system-specifications"),
    ),
)

# Order matters: GoodWe first so it is the default selection in the UI.
BRANDS: dict[str, BrandSpec] = {GOODWE.key: GOODWE, HUAWEI.key: HUAWEI}
DEFAULT_BRAND = GOODWE


@dataclass
class Recommendation:
    best: pd.Series                       # the recommended (cap, power) row
    frontier: pd.DataFrame                # best (max-gain) option per capacity, for "show options"
    max_gain_pick: pd.Series              # the old "biggest gain" pick, for comparison
    gain_max: float
    warnings: list[Msg] = field(default_factory=list)
    notes: list[Msg] = field(default_factory=list)


def _best_per_capacity(results: pd.DataFrame) -> pd.DataFrame:
    """For each capacity, the highest-gain row (its best power). The size/value frontier."""
    idx = results.groupby("Cap_kWh")["Gain_CHF"].idxmax()
    return results.loc[idx].sort_values("Cap_kWh").reset_index(drop=True)


def recommend(
    results: pd.DataFrame,
    gain_threshold: float = 0.90,
    cycles_low: float | None = None,
    cycles_high: float | None = None,
    coverage_days: float | None = None,
    brand: BrandSpec = DEFAULT_BRAND,
    strategy: str = "balanced",
) -> Recommendation:
    """Pick a battery from a grid_search() results table.

    strategy:
      - "cycles"   : largest value while staying above the minimum cycles/year.
      - "gain"     : smallest battery reaching the requested % of maximum gain.
      - "balanced" : smallest battery reaching the requested % of maximum gain;
                     if it also satisfies the cycle floor, ideal. If not, it still
                     avoids absurdly tiny batteries when the site has real surplus.

    gain_threshold is a ratio, e.g. 0.90 = 90% of max gain.
    cycles_low / cycles_high are user-editable from Streamlit.
    """
    warnings: list[Msg] = []
    notes: list[Msg] = []

    if cycles_low is None:
        cycles_low = brand.cycles_low
    if cycles_high is None:
        cycles_high = brand.cycles_high

    strategy = (strategy or "balanced").lower().strip()
    gain_threshold = float(gain_threshold)
    if gain_threshold > 1.0:
        gain_threshold = gain_threshold / 100.0
    gain_threshold = max(0.0, min(1.0, gain_threshold))

    gain_max = float(results["Gain_CHF"].max())
    gain_floor = gain_max * gain_threshold
    frontier = _best_per_capacity(results)
    max_gain_pick = results.sort_values(["Gain_CHF", "Cap_kWh", "Power_kW"],
                                        ascending=[False, True, True]).iloc[0]

    healthy = results[results["Cycles_per_year"] >= cycles_low]
    near_gain = results[results["Gain_CHF"] >= gain_floor] if gain_max > 0 else results.iloc[0:0]
    both = near_gain[near_gain["Cycles_per_year"] >= cycles_low]

    if strategy == "cycles":
        if not healthy.empty:
            top_gain = healthy["Gain_CHF"].max()
            near = healthy[healthy["Gain_CHF"] >= top_gain - 1e-9]
            best = near.sort_values(["Power_kW", "Cap_kWh"]).iloc[0]
            notes.append(("cycles_first", {"cycles_low": cycles_low}))
        else:
            best = results.sort_values("Cycles_per_year", ascending=False).iloc[0]
            warnings.append(("no_healthy", {"cycles_low": cycles_low, "cyc": float(best.Cycles_per_year)}))

    elif strategy == "gain":
        if not near_gain.empty:
            # Smallest battery that reaches the requested share of max savings.
            best = near_gain.sort_values(["Cap_kWh", "Power_kW", "Gain_CHF"],
                                         ascending=[True, True, False]).iloc[0]
        else:
            best = max_gain_pick

    else:  # balanced, default
        if not both.empty:
            # Best practical sales recommendation: enough financial gain, still sufficiently used.
            best = both.sort_values(["Cap_kWh", "Power_kW", "Gain_CHF"],
                                    ascending=[True, True, False]).iloc[0]
        elif not near_gain.empty:
            # If no size can satisfy the cycles floor, avoid the tiny "best cycles" answer and
            # return the smallest battery that captures the requested value.
            best = near_gain.sort_values(["Cap_kWh", "Power_kW", "Gain_CHF"],
                                         ascending=[True, True, False]).iloc[0]
            warnings.append(("no_healthy", {"cycles_low": cycles_low, "cyc": float(best.Cycles_per_year)}))
        elif not healthy.empty:
            top_gain = healthy["Gain_CHF"].max()
            near = healthy[healthy["Gain_CHF"] >= top_gain - 1e-9]
            best = near.sort_values(["Power_kW", "Cap_kWh"]).iloc[0]
        else:
            best = results.sort_values("Cycles_per_year", ascending=False).iloc[0]
            warnings.append(("no_healthy", {"cycles_low": cycles_low, "cyc": float(best.Cycles_per_year)}))

    saved = float(max_gain_pick["Cap_kWh"] - best["Cap_kWh"])
    if saved > 0 and gain_max > 0:
        notes.append(("smaller_than_max", {
            "saved": saved,
            "max_cap": float(max_gain_pick.Cap_kWh),
            "pct": float(best.Gain_CHF / gain_max),
        }))

    # Health label on the chosen battery, using the user's current Streamlit thresholds.
    cyc = float(best["Cycles_per_year"])
    band = {"low": float(cycles_low), "high": float(cycles_high)}
    if cyc < brand.oversized_below:
        warnings.append(("oversized", {"cyc": cyc, **band}))
    elif cyc < cycles_low:
        notes.append(("just_below", {"cyc": cyc, **band}))
    elif cyc <= cycles_high:
        notes.append(("within_band", {"cyc": cyc, **band}))
    else:
        notes.append(("above_band", {"cyc": cyc, **band}))

    if gain_max <= 0:
        warnings.append(("no_savings", {}))

    if coverage_days is not None and coverage_days < 360:
        warnings.append(("partial_year", {"days": float(coverage_days)}))

    return Recommendation(
        best=best,
        frontier=frontier,
        max_gain_pick=max_gain_pick,
        gain_max=gain_max,
        warnings=warnings,
        notes=notes,
    )

if __name__ == "__main__":
    from pathlib import Path
    from loaders import load_meter_file
    from simulation import grid_search

    # Resolve data folder relative to this script, falling back to CWD.
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
    gs = grid_search(
        df.import_kWh.values, df.export_kWh.values,
        caps=range(5, 21), powers=range(3, 11), dt_hours=meta.dt_hours,
        roundtrip_eff=0.92, tariff_import=0.32, tariff_export=0.08,
        coverage_days=meta.coverage_days,
    )
    rec = recommend(gs, coverage_days=meta.coverage_days)
    b, big = rec.best, rec.max_gain_pick
    print(f"Gain max in range: {rec.gain_max:.0f} CHF/yr")
    print(f"RECOMMENDED:      {b.Cap_kWh:.0f} kWh / {b.Power_kW:.0f} kW  "
          f"-> {b.Gain_CHF:.0f} CHF/yr, {b.Cycles_per_year:.0f} cycles/yr")
    print(f"old max-gain pick: {big.Cap_kWh:.0f} kWh / {big.Power_kW:.0f} kW "
          f"-> {big.Gain_CHF:.0f} CHF/yr, {big.Cycles_per_year:.0f} cycles/yr")
    from i18n import msg
    print("\nNotes:", *(msg("en", c, p) for c, p in rec.notes), sep="\n  ")
    print("Warnings:", *([msg("en", c, p) for c, p in rec.warnings] or ["(none)"]), sep="\n  ")

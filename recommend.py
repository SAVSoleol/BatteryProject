"""Tariff-value battery recommendation.

This module no longer recommends a battery from its purchase price or from cycles alone.
The primary decision is the net tariff value calculated by simulation.py:

    gain = avoided import at HT/BT tariffs - lost export revenue

Cycles remain visible as a technical utilization indicator, but they are not the main
selection rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

Msg = tuple[str, dict]

CYCLES_HEALTHY_LOW = 250.0
CYCLES_HEALTHY_HIGH = 300.0
CYCLES_OVERSIZED_BELOW = 150.0


@dataclass(frozen=True)
class BrandSpec:
    key: str
    name: str
    cycles_low: float
    cycles_high: float
    oversized_below: float
    design_cycles_yr: float
    sources: tuple[tuple[str, str], ...]


GOODWE = BrandSpec(
    key="goodwe",
    name="GoodWe Lynx D (GW8.3-BAT)",
    cycles_low=250.0,
    cycles_high=350.0,
    oversized_below=150.0,
    design_cycles_yr=1000.0,
    sources=(
        ("GoodWe Lynx D Series (HV), product page", "https://en.goodwe.com/lynxd"),
        ("GoodWe battery compatibility overview (GW8.3-BAT-D module), PDF", "https://en.goodwe.com/Ftp/EN/Downloads/User%20Manual/GW_Battery%20Compatibility%20Overview-EN.pdf"),
        ("GW8.3-BAT-D-G20 spec & ~10,000-cycle life (reseller listing)", "https://www.solarproof.com.au/products/GW83-BAT-D-G20/"),
        ("GoodWe battery review, Solar Choice (independent)", "https://www.solarchoice.net.au/products/batteries/goodwe-review/"),
    ),
)

HUAWEI = BrandSpec(
    key="huawei",
    name="Huawei (LUNA2000)",
    cycles_low=250.0,
    cycles_high=300.0,
    oversized_below=150.0,
    design_cycles_yr=263.0,
    sources=(
        ("Huawei LUNA2000-7/14/21-S1, spec & warranty", "https://solar.huawei.com/en/products/LUNA2000-7-14-21-S1/specs/"),
        ("Huawei FusionSolar EU warranty conditions, SKE Solar", "https://ske-solar.com/en/support/warranty/huawei-fusionsolar-warranty-conditions/"),
        ("LUNA2000 battery system specifications, Huawei support", "https://support.huawei.com/enterprise/en/doc/EDOC1100186676/661b0e12/luna2000-battery-system-specifications"),
    ),
)

BRANDS: dict[str, BrandSpec] = {GOODWE.key: GOODWE, HUAWEI.key: HUAWEI}
DEFAULT_BRAND = GOODWE


@dataclass
class Recommendation:
    best: pd.Series
    frontier: pd.DataFrame
    max_gain_pick: pd.Series
    gain_max: float
    warnings: list[Msg] = field(default_factory=list)
    notes: list[Msg] = field(default_factory=list)


def _best_per_capacity(results: pd.DataFrame) -> pd.DataFrame:
    """Best power option for each capacity, based on net tariff gain."""
    idx = results.groupby("Cap_kWh")["Gain_CHF"].idxmax()
    return results.loc[idx].sort_values("Cap_kWh").reset_index(drop=True)


def _knee_pick(
    frontier: pd.DataFrame,
    gain_max: float,
    marginal_gain_floor_chf_per_kwh: float = 5.0,
    knee_window_kwh: float = 5.0,
    min_gain_share: float = 0.85,
) -> pd.Series | None:
    """Return the first capacity where extra kWh no longer bring meaningful gain.

    The old method selected the smallest option reaching X% of the best option in the
    tested range. That made the answer depend heavily on Cap. max.

    This method looks at the forward marginal gain: CHF/year added per extra kWh.
    Once the next few kWh add less than `marginal_gain_floor_chf_per_kwh`, the curve
    is considered to have reached its knee / diminishing-return point.
    """
    if frontier.empty or gain_max <= 0:
        return None

    f = frontier.sort_values("Cap_kWh").reset_index(drop=True).copy()
    f["Gain_mono"] = f["Gain_CHF"].cummax()

    for i, row in f.iterrows():
        cap_i = float(row["Cap_kWh"])
        gain_i = float(row["Gain_mono"])

        if gain_i < gain_max * float(min_gain_share):
            continue

        target_cap = cap_i + float(knee_window_kwh)
        future = f[f["Cap_kWh"] >= target_cap]
        if future.empty:
            continue

        j = int(future.index[0])
        cap_j = float(f.loc[j, "Cap_kWh"])
        gain_j = float(f.loc[j, "Gain_mono"])
        if cap_j <= cap_i:
            continue

        marginal = max(0.0, gain_j - gain_i) / (cap_j - cap_i)
        if marginal <= float(marginal_gain_floor_chf_per_kwh):
            # Return the real simulated row for this capacity, not the helper columns.
            return frontier.loc[frontier["Cap_kWh"] == row["Cap_kWh"]].iloc[0]

    return None


def recommend(
    results: pd.DataFrame,
    gain_threshold: float = 0.90,
    cycles_low: float | None = None,
    coverage_days: float | None = None,
    brand: BrandSpec = DEFAULT_BRAND,
    marginal_gain_floor_chf_per_kwh: float = 5.0,
    knee_window_kwh: float = 5.0,
    min_gain_share: float = 0.85,
) -> Recommendation:
    """Pick the battery at the diminishing-return point.

    Selection rule:
      1. keep the best power option for each capacity;
      2. look at the forward marginal gain, in CHF/year per additional kWh;
      3. choose the first capacity where the next kWh add too little value.

    This makes the recommendation much less dependent on the arbitrary Cap. max.
    The `gain_threshold` argument is kept only as a fallback for old callers.
    """

    warnings: list[Msg] = []
    notes: list[Msg] = []

    if results.empty:
        raise ValueError("results table is empty.")

    gain_threshold = float(gain_threshold)
    if gain_threshold > 1.0:
        gain_threshold = gain_threshold / 100.0
    gain_threshold = max(0.0, min(1.0, gain_threshold))

    frontier = _best_per_capacity(results)

    max_gain_pick = results.sort_values(
        ["Gain_CHF", "Cap_kWh", "Power_kW"],
        ascending=[False, True, True],
    ).iloc[0]

    gain_max = float(max_gain_pick["Gain_CHF"])

    if gain_max <= 0:
        best = results.sort_values(["Cap_kWh", "Power_kW"]).iloc[0]
        warnings.append(("no_savings", {}))
    else:
        knee = _knee_pick(
            frontier,
            gain_max,
            marginal_gain_floor_chf_per_kwh=marginal_gain_floor_chf_per_kwh,
            knee_window_kwh=knee_window_kwh,
            min_gain_share=min_gain_share,
        )

        if knee is not None:
            best = knee
        else:
            # Fallback: old 90% rule if the curve has not flattened inside the tested range.
            gain_floor = gain_max * gain_threshold
            candidates = results[results["Gain_CHF"] >= gain_floor].copy()
            if candidates.empty:
                best = max_gain_pick
            else:
                best = candidates.sort_values(
                    ["Cap_kWh", "Power_kW", "Gain_CHF"],
                    ascending=[True, True, False],
                ).iloc[0]

    saved = float(max_gain_pick["Cap_kWh"] - best["Cap_kWh"])
    if saved > 0 and gain_max > 0:
        notes.append(
            (
                "smaller_than_max",
                {
                    "saved": saved,
                    "max_cap": float(max_gain_pick["Cap_kWh"]),
                    "pct": float(best["Gain_CHF"] / gain_max),
                },
            )
        )

    # Cycles are still displayed as technical context, but no longer drive selection.
    if cycles_low is None:
        cycles_low = brand.cycles_low

    cyc = float(best.get("Cycles_per_year", 0.0))
    band = {"low": float(cycles_low), "high": float(brand.cycles_high)}

    # Avoid red "oversized" warnings for normal low-cycle residential cases.
    # Use softer notes so the PDF does not contradict a gain-based recommendation.
    if cyc < cycles_low:
        notes.append(("just_below", {"cyc": cyc, **band}))
    elif cyc <= brand.cycles_high:
        notes.append(("within_band", {"cyc": cyc, **band}))
    else:
        notes.append(("above_band", {"cyc": cyc, **band}))

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
    print("recommend.py OK")

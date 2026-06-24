"""Cycles-aware battery recommendation."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

Msg = tuple[str, dict]

CYCLES_HEALTHY_LOW = 150.0
CYCLES_HEALTHY_HIGH = 350.0
CYCLES_OVERSIZED_BELOW = 100.0


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
    cycles_low=150.0,
    cycles_high=350.0,
    oversized_below=100.0,
    design_cycles_yr=1000.0,
    sources=(
        ("GoodWe Lynx D Series (HV), product page", "https://en.goodwe.com/lynxd"),
        ("GoodWe battery compatibility overview", "https://en.goodwe.com/Ftp/EN/Downloads/User%20Manual/GW_Battery%20Compatibility%20Overview-EN.pdf"),
    ),
)

HUAWEI = BrandSpec(
    key="huawei",
    name="Huawei (LUNA2000)",
    cycles_low=150.0,
    cycles_high=300.0,
    oversized_below=100.0,
    design_cycles_yr=263.0,
    sources=(
        ("Huawei LUNA2000 specs", "https://solar.huawei.com/en/products/LUNA2000-7-14-21-S1/specs/"),
        ("Huawei warranty conditions", "https://ske-solar.com/en/support/warranty/huawei-fusionsolar-warranty-conditions/"),
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
    idx = results.groupby("Cap_kWh")["Gain_CHF"].idxmax()
    return results.loc[idx].sort_values("Cap_kWh").reset_index(drop=True)


def recommend(
    results: pd.DataFrame,
    gain_threshold: float = 0.90,
    cycles_low: float | None = None,
    coverage_days: float | None = None,
    brand: BrandSpec = DEFAULT_BRAND,
    strategy: str = "balanced",
) -> Recommendation:
    warnings: list[Msg] = []
    notes: list[Msg] = []

    if cycles_low is None:
        cycles_low = brand.cycles_low

    gain_max = float(results["Gain_CHF"].max())
    frontier = _best_per_capacity(results)

    max_gain_pick = results.sort_values(
        ["Gain_CHF", "Cap_kWh", "Power_kW"],
        ascending=[False, True, True],
    ).iloc[0]

    if gain_max <= 0:
        best = results.sort_values("Cycles_per_year", ascending=False).iloc[0]
        warnings.append(("no_savings", {}))
    else:
        gain_floor = gain_max * float(gain_threshold)

        if strategy == "gain":
            candidates = results[results["Gain_CHF"] >= gain_floor]
            best = candidates.sort_values(["Cap_kWh", "Power_kW"]).iloc[0]

            notes.append(
                (
                    "gain_mode",
                    {
                        "pct": float(gain_threshold),
                        "gain": float(best.Gain_CHF),
                        "max_gain": float(gain_max),
                    },
                )
            )

        elif strategy == "cycles":
            candidates = results[results["Cycles_per_year"] >= cycles_low]

            if candidates.empty:
                best = results.sort_values("Cycles_per_year", ascending=False).iloc[0]
                warnings.append(
                    (
                        "no_healthy",
                        {
                            "cycles_low": float(cycles_low),
                            "cyc": float(best.Cycles_per_year),
                        },
                    )
                )
            else:
                top_gain = candidates["Gain_CHF"].max()
                near = candidates[candidates["Gain_CHF"] >= top_gain - 1e-9]
                best = near.sort_values(["Power_kW", "Cap_kWh"]).iloc[0]

                notes.append(
                    (
                        "cycles_first",
                        {
                            "cycles_low": float(cycles_low),
                        },
                    )
                )

        else:
            candidates = results[
                (results["Gain_CHF"] >= gain_floor)
                & (results["Cycles_per_year"] >= cycles_low)
            ]

            if not candidates.empty:
                best = candidates.sort_values(["Cap_kWh", "Power_kW"]).iloc[0]

                notes.append(
                    (
                        "balanced_mode",
                        {
                            "pct": float(gain_threshold),
                            "cycles_low": float(cycles_low),
                        },
                    )
                )
            else:
                gain_candidates = results[results["Gain_CHF"] >= gain_floor]

                if not gain_candidates.empty:
                    best = gain_candidates.sort_values(["Cap_kWh", "Power_kW"]).iloc[0]

                    notes.append(
                        (
                            "balanced_gain_fallback",
                            {
                                "pct": float(gain_threshold),
                                "cycles_low": float(cycles_low),
                                "cyc": float(best.Cycles_per_year),
                            },
                        )
                    )
                else:
                    best = results.sort_values("Cycles_per_year", ascending=False).iloc[0]

                    warnings.append(
                        (
                            "no_healthy",
                            {
                                "cycles_low": float(cycles_low),
                                "cyc": float(best.Cycles_per_year),
                            },
                        )
                    )

    cyc = float(best["Cycles_per_year"])

    band = {
        "low": float(cycles_low),
        "high": float(brand.cycles_high),
    }

    if cyc < brand.oversized_below:
        warnings.append(("oversized", {"cyc": cyc, **band}))
    elif cyc < cycles_low:
        notes.append(("just_below", {"cyc": cyc, **band}))
    elif cyc <= brand.cycles_high:
        notes.append(("within_band", {"cyc": cyc, **band}))
    else:
        notes.append(("above_band", {"cyc": cyc, **band}))

    saved = float(max_gain_pick["Cap_kWh"] - best["Cap_kWh"])
    if saved > 0 and gain_max > 0:
        notes.append(
            (
                "smaller_than_max",
                {
                    "saved": saved,
                    "max_cap": float(max_gain_pick.Cap_kWh),
                    "pct": float(best.Gain_CHF / gain_max),
                },
            )
        )

    # Couverture des données :
    # >330 jours : pas d'avertissement
    # 180-330 jours : avertissement léger
    # <180 jours : avertissement plus important
    if coverage_days is not None:
        days = float(coverage_days)

        if days < 180:
            warnings.append(("partial_year_strong", {"days": days}))
        elif days < 330:
            warnings.append(("partial_year", {"days": days}))

    return Recommendation(
        best=best,
        frontier=frontier,
        max_gain_pick=max_gain_pick,
        gain_max=gain_max,
        warnings=warnings,
        notes=notes,
    )

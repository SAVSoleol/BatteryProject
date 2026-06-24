"""Multi-vendor meter-data loaders.

Every client file (Huawei / Groupe E / SolarEdge), regardless of separator, units, or
layout, is normalized to ONE internal shape:

    a DataFrame with columns  [timestamp, import_kWh, export_kWh]  per interval,

plus a `Meta` describing what was detected. The simulation never sees vendor quirks.

Units zoo handled here (see PROJECT_NOTES.md §4-5):
  - Huawei  .xlsx : CUMULATIVE kWh registers -> differenced. Column names are reversed:
                    "Énergie active négative" = IMPORT, "positive" = EXPORT.
  - Groupe E .xlsx : kW (power)  -> x dt_hours to get kWh.
  - SolarEdge .csv : Wh per interval -> / 1000.
  - Groupe E .csv  : Wh per interval -> / 1000 (column order reversed vs SolarEdge).
  - Romande Energie .csv : NO export column -> unsupported (raise), not a battery candidate.
"""

from __future__ import annotations

import warnings
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

STD_COLS = ["timestamp", "import_kWh", "export_kWh"]

# openpyxl warns on the Huawei workbooks ("no default style"), harmless noise.
warnings.filterwarnings("ignore", message="Workbook contains no default style")


class UnsupportedFormatError(ValueError):
    """Raised for files we deliberately do not support (e.g. no export column)."""


@dataclass
class Meta:
    vendor: str
    dt_hours: float
    n_rows: int
    coverage_days: float
    source: str


# --------------------------------------------------------------------------- helpers
def _norm(text) -> str:
    """Lowercase + strip accents, for robust header matching across vendors."""
    s = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _find_col(cols, *tokens) -> str | None:
    """First column whose normalized name contains ALL given tokens."""
    for c in cols:
        n = _norm(c)
        if all(t in n for t in tokens):
            return c
    return None


def _infer_dt_hours(ts: pd.Series) -> float:
    """Median spacing between timestamps, in hours (e.g. 0.25 for 15-min data)."""
    diffs = ts.sort_values().diff().dropna()
    if diffs.empty:
        return 0.25
    return float(diffs.median().total_seconds() / 3600.0)


def _finalize(df: pd.DataFrame, vendor: str, source: str) -> tuple[pd.DataFrame, Meta]:
    """Common cleanup: drop bad timestamps, sort, dedupe, clamp negatives, build Meta."""
    df = df.dropna(subset=["timestamp"]).copy()
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for c in ("import_kWh", "export_kWh"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).clip(lower=0.0)
    dt = _infer_dt_hours(df["timestamp"])
    span = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) if len(df) else pd.Timedelta(0)
    meta = Meta(
        vendor=vendor,
        dt_hours=round(dt, 6),
        n_rows=len(df),
        coverage_days=round(span.total_seconds() / 86400.0, 1),
        source=source,
    )
    return df[STD_COLS], meta


# --------------------------------------------------------------------------- detection
def detect_vendor(path: str | Path) -> str:
    """Sniff the vendor from extension + header content."""
    path = Path(path)
    ext = path.suffix.lower()

    if ext in (".xlsx", ".xls"):
        head = pd.read_excel(path, header=None, nrows=12)
        blob = " | ".join(_norm(v) for v in head.values.ravel())
        if "energie active negative" in blob or "energie active positive" in blob:
            return "huawei"
        if "soutirage" in blob and "surplus" in blob:
            return "groupe_e_xlsx"
        raise UnsupportedFormatError(f"Unknown Excel layout: {path.name}")

    if ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            header = _norm(fh.readline())
        # SolarEdge: comma-separated, energy in Wh, has both import & export
        if "energie (wh)" in header and "import" in header:
            return "solaredge_csv"
        # Groupe E chart export: "Export en Wh" / "Import en Wh"
        if "export en wh" in header and "import en wh" in header:
            return "groupe_e_csv"
        # Romande Energie: semicolon, consumption only, NO export -> unsupported
        if "consommation" in header and "surplus" not in header and "export" not in header:
            raise UnsupportedFormatError(
                f"{path.name}: consumption-only file (no export column), not a battery candidate."
            )
        raise UnsupportedFormatError(f"Unknown CSV layout: {path.name}")

    raise UnsupportedFormatError(f"Unsupported file type: {path.name}")


# --------------------------------------------------------------------------- per-vendor
def _load_huawei(path: Path) -> pd.DataFrame:
    """Huawei monthly export: header on row 4; cumulative kWh registers -> diff.

    négative = grid import, positive = export (verified by winter/summer deltas).
    """
    df = pd.read_excel(path, header=3)
    date_col = _find_col(df.columns, "heure", "debut") or _find_col(df.columns, "heure")
    imp_col = _find_col(df.columns, "negativ")   # cumulative IMPORT register
    exp_col = _find_col(df.columns, "positiv")   # cumulative EXPORT register
    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Huawei columns not found in {path.name}")

    # Summer exports append a DST/timezone flag, e.g. "2025-07-01 00:00:00 DST",
    # which breaks parsing. Strip any trailing alpha timezone token first.
    ts_clean = df[date_col].astype(str).str.replace(
        r"\s*(DST|CEST|CET|UTC|ST)\s*$", "", regex=True
    )
    ts = pd.to_datetime(ts_clean, errors="coerce")
    imp_cum = pd.to_numeric(df[imp_col], errors="coerce")
    exp_cum = pd.to_numeric(df[exp_col], errors="coerce")

    # Difference the cumulative registers, per device if several are present.
    dev_col = _find_col(df.columns, "appareil")
    work = pd.DataFrame({"timestamp": ts, "imp_cum": imp_cum, "exp_cum": exp_cum})
    if dev_col:
        work["dev"] = df[dev_col]
    else:
        work["dev"] = "single"
    work = work.dropna(subset=["timestamp"]).sort_values(["dev", "timestamp"])

    work["import_kWh"] = work.groupby("dev")["imp_cum"].diff()
    work["export_kWh"] = work.groupby("dev")["exp_cum"].diff()
    # First reading per device has no predecessor -> NaN; meter resets -> negative; clamp.
    work["import_kWh"] = work["import_kWh"].clip(lower=0)
    work["export_kWh"] = work["export_kWh"].clip(lower=0)
    return work.dropna(subset=["import_kWh", "export_kWh"])[["timestamp", "import_kWh", "export_kWh"]]


def _load_groupe_e_xlsx(path: Path) -> pd.DataFrame:
    """Groupe E meter export: header on the row containing 'Soutirage'; values in kW."""
    head = pd.read_excel(path, header=None, nrows=15)
    header_row = next(
        (i for i in range(len(head)) if "soutirage" in " | ".join(_norm(v) for v in head.iloc[i])),
        None,
    )
    if header_row is None:
        raise UnsupportedFormatError(f"Groupe E header row not found in {path.name}")
    df = pd.read_excel(path, header=header_row)

    date_col = _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "soutirage")        # import, kW
    exp_col = _find_col(df.columns, "surplus")          # export, kW
    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Groupe E columns not found in {path.name}")

    ts = pd.to_datetime(df[date_col], errors="coerce")
    dt = _infer_dt_hours(ts.dropna())
    imp_kw = pd.to_numeric(df[imp_col], errors="coerce").fillna(0.0)
    exp_kw = pd.to_numeric(df[exp_col], errors="coerce").fillna(0.0)  # NaN at night -> 0
    return pd.DataFrame(
        {"timestamp": ts, "import_kWh": imp_kw * dt, "export_kWh": exp_kw * dt}
    )


def _load_solaredge_csv(path: Path) -> pd.DataFrame:
    """SolarEdge chart export: comma-sep, energy in Wh, dayfirst dates."""
    df = pd.read_csv(path, sep=",", encoding="utf-8-sig")
    date_col = _find_col(df.columns, "time") or _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "import")
    exp_col = _find_col(df.columns, "export")
    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"SolarEdge columns not found in {path.name}")
    ts = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce") / 1000.0,
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce") / 1000.0,
        }
    )


def _load_groupe_e_csv(path: Path) -> pd.DataFrame:
    """Groupe E chart export: comma-sep, energy in Wh, columns 'Export en Wh'/'Import en Wh'."""
    df = pd.read_csv(path, sep=",", encoding="utf-8-sig")
    date_col = _find_col(df.columns, "date") or _find_col(df.columns, "time")
    imp_col = _find_col(df.columns, "import")
    exp_col = _find_col(df.columns, "export")
    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Groupe E CSV columns not found in {path.name}")
    ts = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce") / 1000.0,
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce") / 1000.0,
        }
    )


_LOADERS = {
    "huawei": _load_huawei,
    "groupe_e_xlsx": _load_groupe_e_xlsx,
    "solaredge_csv": _load_solaredge_csv,
    "groupe_e_csv": _load_groupe_e_csv,
}


# --------------------------------------------------------------------------- public API
def load_meter_file(path: str | Path) -> tuple[pd.DataFrame, Meta]:
    """Load and normalize a single meter file. Raises UnsupportedFormatError if unsupported."""
    path = Path(path)
    vendor = detect_vendor(path)
    df = _LOADERS[vendor](path)
    return _finalize(df, vendor, path.name)


def load_meter_files(paths) -> tuple[pd.DataFrame, Meta]:
    """Load several files (e.g. 12 Huawei monthly files) and concatenate into one series."""
    frames, vendors, sources = [], set(), []
    for p in paths:
        df, m = load_meter_file(p)
        frames.append(df)
        vendors.add(m.vendor)
        sources.append(m.source)
    combined = pd.concat(frames, ignore_index=True)
    vendor = next(iter(vendors)) if len(vendors) == 1 else "mixed(" + ",".join(sorted(vendors)) + ")"
    return _finalize(combined, vendor, "; ".join(sources))


# --------------------------------------------------------------------------- self-check
if __name__ == "__main__":
    import sys

    # Resolve data folder relative to this script, falling back to CWD, then CLI arg.
    script_dir = Path(__file__).resolve().parent
    candidates = [Path("data/battery_data"), script_dir / "data" / "battery_data"]
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else next((c for c in candidates if c.is_dir()), candidates[0])
    print(f"Scanning {base}\n" + "=" * 78)
    huawei_months = sorted(base.glob("*.xlsx"))
    for f in sorted(base.iterdir()):
        if f.name.endswith("Zone.Identifier") or f.is_dir():
            continue
        try:
            df, m = load_meter_file(f)
            print(
                f"OK   {f.name[:46]:46} | {m.vendor:14} | dt={m.dt_hours:.3f}h "
                f"| rows={m.n_rows:6} | {m.coverage_days:6.1f}d "
                f"| imp={df.import_kWh.sum():9.1f} exp={df.export_kWh.sum():9.1f} kWh"
            )
        except UnsupportedFormatError as e:
            print(f"SKIP {f.name[:46]:46} | {e}")

    # Demonstrate combining the 12 Huawei monthly files into one annual series.
    months = [f for f in huawei_months if detect_vendor(f) == "huawei"] if huawei_months else []
    if months:
        df, m = load_meter_files(months)
        print("=" * 78)
        print(
            f"Huawei COMBINED {len(months)} files -> rows={m.n_rows}, {m.coverage_days:.0f} days, "
            f"import={df.import_kWh.sum():.0f} kWh, export={df.export_kWh.sum():.0f} kWh"
        )

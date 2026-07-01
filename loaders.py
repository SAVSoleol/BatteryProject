"""Multi-vendor meter-data loaders.

Supported inputs:
- Huawei Excel cumulative active energy exports
- Groupe E Excel / CSV
- SolarEdge CSV
- Romande Energie CSV
- Generic Excel / CSV with Date + Import + Export columns

All returned values are normalized to interval kWh.
"""

from __future__ import annotations

import warnings
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

STD_COLS = ["timestamp", "import_kWh", "export_kWh"]

warnings.filterwarnings("ignore", message="Workbook contains no default style")


class UnsupportedFormatError(ValueError):
    """Raised for unsupported files."""


@dataclass
class Meta:
    vendor: str
    dt_hours: float
    n_rows: int
    coverage_days: float
    source: str
    data_unit: str = "kWh"


def _norm(text) -> str:
    s = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _find_col(cols, *tokens) -> str | None:
    for c in cols:
        n = _norm(c)
        if all(t in n for t in tokens):
            return c
    return None


def _find_any_col(cols, token_groups) -> str | None:
    """Find first column matching any group of required tokens.

    Example token_groups: [("date",), ("time",), ("horodat",)]
    """
    for group in token_groups:
        found = _find_col(cols, *group)
        if found is not None:
            return found
    return None


def _parse_datetime(series: pd.Series, dayfirst: bool = True) -> pd.Series:
    """Parse timestamps robustly, including mixed CET/CEST timezone offsets."""
    return pd.to_datetime(
        series,
        errors="coerce",
        dayfirst=dayfirst,
        utc=True,
    ).dt.tz_convert(None)


def _infer_dt_hours(ts: pd.Series) -> float:
    diffs = ts.sort_values().diff().dropna()
    if diffs.empty:
        return 0.25
    return float(diffs.median().total_seconds() / 3600.0)


DEFAULT_UNITS = {
    "huawei": "kWh",
    "groupe_e_xlsx": "kW",
    "solaredge_csv": "Wh",
    "groupe_e_csv": "Wh",
    "romande_energie_csv": "kWh",
    "generic_excel": "kWh",
    "generic_csv": "kWh",
}

UNIT_OPTIONS = ("auto", "kWh", "kW", "Wh", "W")


def _normalize_unit(unit: str | None) -> str:
    if unit is None:
        return "auto"
    unit = str(unit).strip()
    aliases = {
        "Automatique": "auto",
        "automatique": "auto",
        "automatic": "auto",
        "Auto": "auto",
        "AUTO": "auto",
        "KWH": "kWh",
        "kwH": "kWh",
        "KWh": "kWh",
        "kwh": "kWh",
        "KW": "kW",
        "kw": "kW",
        "WH": "Wh",
        "wh": "Wh",
        "w": "W",
    }
    unit = aliases.get(unit, unit)
    if unit not in UNIT_OPTIONS:
        raise UnsupportedFormatError(
            f"Unknown unit '{unit}'. Expected one of: auto, kWh, kW, Wh, W."
        )
    return unit


def _detect_unit_from_columns(*cols) -> str:
    """Best-effort unit detection from column names.

    If unsure, return kWh because most generic files already contain interval energy.
    The user can still force kW / W / Wh from the sidebar.
    """
    blob = " | ".join(_norm(c).replace(" ", "") for c in cols if c is not None)

    if "kwh" in blob:
        return "kWh"
    # Check Wh after kWh, otherwise kWh would also match Wh.
    if "wh" in blob:
        return "Wh"
    if "kw" in blob:
        return "kW"
    # Avoid treating every word containing w as watts; require a clear unit marker.
    if "(w)" in blob or "_w" in blob or "enw" in blob or blob.endswith("w"):
        return "W"
    return "kWh"


def _convert_to_kwh(df: pd.DataFrame, unit: str, dt_hours: float) -> pd.DataFrame:
    """Convert the raw import/export values to kWh.

    kWh / Wh are interval energies.
    kW / W are average powers over the interval and must be multiplied by dt_hours.
    """
    df = df.copy()

    if unit == "kWh":
        factor = 1.0
    elif unit == "Wh":
        factor = 1.0 / 1000.0
    elif unit == "kW":
        factor = float(dt_hours)
    elif unit == "W":
        factor = float(dt_hours) / 1000.0
    else:
        raise UnsupportedFormatError(f"Unit conversion not supported for '{unit}'.")

    df["import_kWh"] = df["import_kWh"] * factor
    df["export_kWh"] = df["export_kWh"] * factor
    return df


def _finalize(
    df: pd.DataFrame,
    vendor: str,
    source: str,
    data_unit: str = "auto",
    default_unit: str | None = None,
) -> tuple[pd.DataFrame, Meta]:
    df = df.dropna(subset=["timestamp"]).copy()
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)

    for c in ("import_kWh", "export_kWh"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).clip(lower=0.0)

    dt = _infer_dt_hours(df["timestamp"])

    data_unit = _normalize_unit(data_unit)
    effective_unit = default_unit or DEFAULT_UNITS.get(vendor, "kWh")
    if data_unit != "auto":
        effective_unit = data_unit

    df = _convert_to_kwh(df, effective_unit, dt)

    span = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) if len(df) else pd.Timedelta(0)

    meta = Meta(
        vendor=vendor,
        dt_hours=round(dt, 6),
        n_rows=len(df),
        coverage_days=round(span.total_seconds() / 86400.0, 1),
        source=source,
        data_unit=effective_unit,
    )

    return df[STD_COLS], meta


def _generic_cols(cols) -> tuple[str | None, str | None, str | None]:
    date_col = _find_any_col(
        cols,
        [
            ("date",),
            ("time",),
            ("timestamp",),
            ("horodat",),
            ("heure",),
            ("debut",),
        ],
    )
    imp_col = _find_any_col(
        cols,
        [
            ("import",),
            ("soutirage",),
            ("consommation",),
            ("achat",),
            ("prelev",),
            ("prelevement",),
        ],
    )
    exp_col = _find_any_col(
        cols,
        [
            ("export",),
            ("surplus",),
            ("excedent",),
            ("refoule",),
            ("refoulee",),
            ("revente",),
            ("injection",),
        ],
    )
    return date_col, imp_col, exp_col


def _find_generic_excel_header_row(path: Path, max_rows: int = 25) -> int | None:
    """Find the row containing Date + Import + Export headers in an Excel file."""
    preview = pd.read_excel(path, header=None, nrows=max_rows)
    for i in range(len(preview)):
        row_values = [v for v in preview.iloc[i].tolist() if str(v).strip() and str(v) != "nan"]
        if not row_values:
            continue
        date_col, imp_col, exp_col = _generic_cols(row_values)
        if date_col and imp_col and exp_col:
            return i
    return None


def _read_csv_auto(path: Path, nrows: int | None = None) -> pd.DataFrame:
    """Read CSV with automatic separator detection."""
    return pd.read_csv(
        path,
        sep=None,
        engine="python",
        encoding="utf-8-sig",
        nrows=nrows,
    )


def detect_vendor(path: str | Path) -> str:
    path = Path(path)
    ext = path.suffix.lower()

    if ext in (".xlsx", ".xls"):
        head = pd.read_excel(path, header=None, nrows=12)
        blob = " | ".join(_norm(v) for v in head.values.ravel())

        if "energie active negative" in blob or "energie active positive" in blob:
            return "huawei"

        if "soutirage" in blob and "surplus" in blob:
            return "groupe_e_xlsx"

        # Generic Excel fallback: Date + Import + Export columns.
        if _find_generic_excel_header_row(path) is not None:
            return "generic_excel"

        raise UnsupportedFormatError(f"Unknown Excel layout: {path.name}")

    if ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            header = _norm(fh.readline())

        if "energie (wh)" in header and "import" in header:
            return "solaredge_csv"

        if "export en wh" in header and "import en wh" in header:
            return "groupe_e_csv"

        if "consommation" in header and "excedent" in header:
            return "romande_energie_csv"

        if (
            "consommation" in header
            and "surplus" not in header
            and "export" not in header
            and "excedent" not in header
        ):
            raise UnsupportedFormatError(
                f"{path.name}: consumption-only file (no export column), not a battery candidate."
            )

        # Generic CSV fallback: Date + Import + Export columns, any common separator.
        try:
            preview = _read_csv_auto(path, nrows=5)
            date_col, imp_col, exp_col = _generic_cols(preview.columns)
            if date_col and imp_col and exp_col:
                return "generic_csv"
        except Exception:
            pass

        raise UnsupportedFormatError(f"Unknown CSV layout: {path.name}")

    raise UnsupportedFormatError(f"Unsupported file type: {path.name}")


def _load_huawei(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, header=3)

    date_col = _find_col(df.columns, "heure", "debut") or _find_col(df.columns, "heure")
    imp_col = _find_col(df.columns, "negativ")
    exp_col = _find_col(df.columns, "positiv")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Huawei columns not found in {path.name}")

    ts_clean = df[date_col].astype(str).str.replace(
        r"\s*(DST|CEST|CET|UTC|ST)\s*$", "", regex=True
    )
    ts = _parse_datetime(ts_clean, dayfirst=False)

    imp_cum = pd.to_numeric(df[imp_col], errors="coerce")
    exp_cum = pd.to_numeric(df[exp_col], errors="coerce")

    dev_col = _find_col(df.columns, "appareil")
    work = pd.DataFrame({"timestamp": ts, "imp_cum": imp_cum, "exp_cum": exp_cum})
    work["dev"] = df[dev_col] if dev_col else "single"

    work = work.dropna(subset=["timestamp"]).sort_values(["dev", "timestamp"])

    work["import_kWh"] = work.groupby("dev")["imp_cum"].diff()
    work["export_kWh"] = work.groupby("dev")["exp_cum"].diff()

    work["import_kWh"] = work["import_kWh"].clip(lower=0)
    work["export_kWh"] = work["export_kWh"].clip(lower=0)

    return work.dropna(subset=["import_kWh", "export_kWh"])[
        ["timestamp", "import_kWh", "export_kWh"]
    ]


def _load_groupe_e_xlsx(path: Path) -> pd.DataFrame:
    head = pd.read_excel(path, header=None, nrows=15)

    header_row = next(
        (
            i
            for i in range(len(head))
            if "soutirage" in " | ".join(_norm(v) for v in head.iloc[i])
        ),
        None,
    )

    if header_row is None:
        raise UnsupportedFormatError(f"Groupe E header row not found in {path.name}")

    df = pd.read_excel(path, header=header_row)

    date_col = _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "soutirage")
    exp_col = _find_col(df.columns, "surplus")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Groupe E columns not found in {path.name}")

    ts = _parse_datetime(df[date_col], dayfirst=True)

    imp_kw = pd.to_numeric(df[imp_col], errors="coerce").fillna(0.0)
    exp_kw = pd.to_numeric(df[exp_col], errors="coerce").fillna(0.0)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": imp_kw,
            "export_kWh": exp_kw,
        }
    )


def _load_solaredge_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=",", encoding="utf-8-sig")

    date_col = _find_col(df.columns, "time") or _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "import")
    exp_col = _find_col(df.columns, "export")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"SolarEdge columns not found in {path.name}")

    ts = _parse_datetime(df[date_col], dayfirst=True)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


def _load_groupe_e_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=",", encoding="utf-8-sig")

    date_col = _find_col(df.columns, "date") or _find_col(df.columns, "time")
    imp_col = _find_col(df.columns, "import")
    exp_col = _find_col(df.columns, "export")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Groupe E CSV columns not found in {path.name}")

    ts = _parse_datetime(df[date_col], dayfirst=True)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


def _load_romande_energie_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")

    date_col = _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "consommation")
    exp_col = _find_col(df.columns, "excedent")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Romande Energie columns not found in {path.name}")

    ts = _parse_datetime(df[date_col], dayfirst=True)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


def _load_generic_excel(path: Path) -> pd.DataFrame:
    header_row = _find_generic_excel_header_row(path)
    if header_row is None:
        raise UnsupportedFormatError(f"Generic Excel columns not found in {path.name}")

    df = pd.read_excel(path, header=header_row)
    date_col, imp_col, exp_col = _generic_cols(df.columns)

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Generic Excel columns not found in {path.name}")

    return pd.DataFrame(
        {
            "timestamp": _parse_datetime(df[date_col], dayfirst=True),
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


def _load_generic_csv(path: Path) -> pd.DataFrame:
    df = _read_csv_auto(path)
    date_col, imp_col, exp_col = _generic_cols(df.columns)

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Generic CSV columns not found in {path.name}")

    return pd.DataFrame(
        {
            "timestamp": _parse_datetime(df[date_col], dayfirst=True),
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


def _default_unit_for_loaded_file(vendor: str, raw_df: pd.DataFrame | None = None) -> str:
    if vendor in ("generic_excel", "generic_csv") and raw_df is not None:
        _, imp_col, exp_col = _generic_cols(raw_df.columns)
        return _detect_unit_from_columns(imp_col, exp_col)
    return DEFAULT_UNITS.get(vendor, "kWh")


_LOADERS = {
    "huawei": _load_huawei,
    "groupe_e_xlsx": _load_groupe_e_xlsx,
    "solaredge_csv": _load_solaredge_csv,
    "groupe_e_csv": _load_groupe_e_csv,
    "romande_energie_csv": _load_romande_energie_csv,
    "generic_excel": _load_generic_excel,
    "generic_csv": _load_generic_csv,
}


def load_meter_file(path: str | Path, data_unit: str = "auto") -> tuple[pd.DataFrame, Meta]:
    path = Path(path)
    vendor = detect_vendor(path)
    df = _LOADERS[vendor](path)

    # For generic files, detect kWh / Wh / kW / W from the original column names.
    default_unit = DEFAULT_UNITS.get(vendor, "kWh")
    if vendor == "generic_excel":
        header_row = _find_generic_excel_header_row(path)
        raw = pd.read_excel(path, header=header_row) if header_row is not None else None
        default_unit = _default_unit_for_loaded_file(vendor, raw)
    elif vendor == "generic_csv":
        raw = _read_csv_auto(path, nrows=5)
        default_unit = _default_unit_for_loaded_file(vendor, raw)

    return _finalize(
        df,
        vendor,
        path.name,
        data_unit=data_unit,
        default_unit=default_unit,
    )


def load_meter_files(paths, data_unit: str = "auto") -> tuple[pd.DataFrame, Meta]:
    frames, vendors, sources = [], set(), []

    for p in paths:
        df, m = load_meter_file(p, data_unit=data_unit)
        frames.append(df)
        vendors.add(m.vendor)
        sources.append(m.source)

    combined = pd.concat(frames, ignore_index=True)
    vendor = next(iter(vendors)) if len(vendors) == 1 else "mixed(" + ",".join(sorted(vendors)) + ")"

    # Files are already converted to kWh by load_meter_file, so do not reconvert.
    return _finalize(combined, vendor, "; ".join(sources), data_unit="kWh", default_unit="kWh")


if __name__ == "__main__":
    print("loaders.py OK")

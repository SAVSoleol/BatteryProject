"""Multi-vendor meter-data loaders."""

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


def _norm(text) -> str:
    s = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _find_col(cols, *tokens) -> str | None:
    for c in cols:
        n = _norm(c)
        if all(t in n for t in tokens):
            return c
    return None


def _infer_dt_hours(ts: pd.Series) -> float:
    diffs = ts.sort_values().diff().dropna()
    if diffs.empty:
        return 0.25
    return float(diffs.median().total_seconds() / 3600.0)


def _finalize(df: pd.DataFrame, vendor: str, source: str) -> tuple[pd.DataFrame, Meta]:
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

        if "consommation" in header and "surplus" not in header and "export" not in header and "excedent" not in header:
            raise UnsupportedFormatError(
                f"{path.name}: consumption-only file (no export column), not a battery candidate."
            )

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
    ts = pd.to_datetime(ts_clean, errors="coerce")

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

    ts = pd.to_datetime(df[date_col], errors="coerce")
    dt = _infer_dt_hours(ts.dropna())

    imp_kw = pd.to_numeric(df[imp_col], errors="coerce").fillna(0.0)
    exp_kw = pd.to_numeric(df[exp_col], errors="coerce").fillna(0.0)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": imp_kw * dt,
            "export_kWh": exp_kw * dt,
        }
    )


def _load_solaredge_csv(path: Path) -> pd.DataFrame:
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


def _load_romande_energie_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")

    date_col = _find_col(df.columns, "date")
    imp_col = _find_col(df.columns, "consommation")
    exp_col = _find_col(df.columns, "excedent")

    if not (date_col and imp_col and exp_col):
        raise UnsupportedFormatError(f"Romande Energie columns not found in {path.name}")

    ts = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)

    return pd.DataFrame(
        {
            "timestamp": ts,
            "import_kWh": pd.to_numeric(df[imp_col], errors="coerce"),
            "export_kWh": pd.to_numeric(df[exp_col], errors="coerce"),
        }
    )


_LOADERS = {
    "huawei": _load_huawei,
    "groupe_e_xlsx": _load_groupe_e_xlsx,
    "solaredge_csv": _load_solaredge_csv,
    "groupe_e_csv": _load_groupe_e_csv,
    "romande_energie_csv": _load_romande_energie_csv,
}


def load_meter_file(path: str | Path) -> tuple[pd.DataFrame, Meta]:
    path = Path(path)
    vendor = detect_vendor(path)
    df = _LOADERS[vendor](path)
    return _finalize(df, vendor, path.name)


def load_meter_files(paths) -> tuple[pd.DataFrame, Meta]:
    frames, vendors, sources = [], set(), []

    for p in paths:
        df, m = load_meter_file(p)
        frames.append(df)
        vendors.add(m.vendor)
        sources.append(m.source)

    combined = pd.concat(frames, ignore_index=True)
    vendor = next(iter(vendors)) if len(vendors) == 1 else "mixed(" + ",".join(sorted(vendors)) + ")"

    return _finalize(combined, vendor, "; ".join(sources))

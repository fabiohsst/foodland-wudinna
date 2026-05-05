"""
predict.py — LightGBM inference for the Fruit & Veg Order Sheet Generator
Foodland Wudinna

Design principle: load model weights and item statistics from the pkl, but
compute same-weekday lags from live sales data. This means the forecast stays
accurate week-to-week without retraining the model.

Usage (from app.py):
    from predict import load_model, predict_cycle
    model_data = load_model()                              # cached
    forecast_df, labels = predict_cycle(
        cycle_dates, specials_list, model_data, all_sales_df
    )
"""

import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT             = Path(__file__).parent
MODEL_PKL        = ROOT / "03_model" / "demand_model.pkl"
SENSITIVITY_CSV  = ROOT / "01_data" / "reference" / "item_price_sensitivity.csv"
SUPPLIER_DIR     = ROOT / "01_data" / "operational"

DEFAULT_MARGIN   = 0.40    # fallback gross margin for sell price estimation


def _norm(s: str) -> str:
    """Collapse embedded newlines and extra whitespace (mirrors POS export quirks)."""
    return re.sub(r"\s+", " ", str(s)).strip()


def load_model() -> dict:
    """
    Load the trained model pkl.

    Returns a dict with keys:
        model, feature_cols, item_stats (DataFrame), item_dow (DataFrame),
        active_items (list), alpha, season_map, public_holidays
    """
    with open(MODEL_PKL, "rb") as f:
        raw = pickle.load(f)

    # Normalise item names stored in the pkl (training-time names may have
    # embedded newlines from the POS export).
    stats = raw["item_stats"].copy()
    stats["Name"] = stats["Name"].apply(_norm)

    idow = raw["item_dow"].copy()
    idow["Name"] = idow["Name"].apply(_norm)

    active = [_norm(n) for n in raw["active_items"]]

    # public_holidays may be a set of Timestamps or date objects — normalise to
    # a set of pd.Timestamp for consistent comparison.
    pub_hols = set(pd.Timestamp(h) for h in raw["public_holidays"])

    return {
        "model":        raw["model"],
        "feature_cols": raw["feature_cols"],
        "item_stats":   stats,
        "item_dow":     idow,
        "active_items": active,
        "alpha":        raw["alpha"],
        "season_map":   raw["season_map"],
        "public_holidays": pub_hols,
        "trained_on":   raw.get("trained_on"),
    }


def load_price_sensitivity() -> dict:
    """
    Load item_price_sensitivity.csv → {normalised_name: (is_price_sensitive, avg_sell_price)}.

    Returns an empty dict if the file doesn't exist (graceful fallback: all items
    treated as neutral, price_ratio defaults to 1.0).
    """
    if not SENSITIVITY_CSV.exists():
        return {}
    df = pd.read_csv(SENSITIVITY_CSV)
    df["Name"] = df["Name"].apply(_norm)
    return {
        row["Name"]: {
            "is_price_sensitive": int(row["is_price_sensitive"]),
            "avg_sell_price":     float(row["item_avg_sell_price"]),
        }
        for _, row in df.iterrows()
    }


def load_supplier_prices(cycle_week_start: pd.Timestamp) -> dict:
    """
    Look for supplier_prices_YYYYMMDD.csv in 01_data/operational/ where the
    date matches the delivery week_start.

    Returns {normalised_name: sell_price} when found, empty dict otherwise.
    The app continues normally with the sales-data fallback when no file exists.
    """
    # Find the file whose date is within ±3 days of the cycle week start
    candidates = sorted(SUPPLIER_DIR.glob("supplier_prices_*.csv"), reverse=True)
    for path in candidates:
        try:
            file_date = pd.Timestamp(path.stem.replace("supplier_prices_", ""))
            if abs((file_date - cycle_week_start).days) <= 3:
                df = pd.read_csv(path)
                df["Name"] = df["Name"].apply(_norm)
                df["sell_price"] = pd.to_numeric(df["sell_price"], errors="coerce")
                df = df.dropna(subset=["sell_price"])
                return dict(zip(df["Name"], df["sell_price"]))
        except Exception:
            continue
    return {}


def predict_cycle(
    cycle_dates: list,
    specials: list,
    model_data: dict,
    all_sales: pd.DataFrame,
    active_filter: set | None = None,
) -> tuple[pd.DataFrame, list]:
    """
    Generate LightGBM demand forecasts for a set of cycle dates.

    Parameters
    ----------
    cycle_dates : list[pd.Timestamp]
        Store-open trading days to forecast (coverage period).
    specials : list[str]
        Item names flagged as on special this cycle.
    model_data : dict
        Output of load_model().
    all_sales : pd.DataFrame
        Full historical sales with columns: Name (normalised), Date, Quantity.
        Used to compute fresh same-weekday lags.
    active_filter : set[str] | None
        If provided, only items in this set are forecast. Intended to be
        items sold in the last 2 weeks plus any specials. Items not in this
        set are silently skipped, keeping the output lean.

    Returns
    -------
    forecast_df : pd.DataFrame
        Columns: Name | <day_label> ... | Total Forecast
    cycle_labels : list[str]
        Column labels matching the day columns.
    """
    model        = model_data["model"]
    feature_cols = model_data["feature_cols"]
    alpha        = model_data["alpha"]
    season_map   = model_data["season_map"]
    pub_hols     = model_data["public_holidays"]

    # Apply prefilter: model's training items ∩ recently-sold items ∪ specials
    all_model_items = model_data["active_items"]
    if active_filter is not None:
        specials_set_norm = set(specials)
        active_items = [
            i for i in all_model_items
            if i in active_filter or i in specials_set_norm
        ]
    else:
        active_items = all_model_items

    # Build fast lookup structures from item_stats and item_dow DataFrames.
    istats_map: dict[str, dict] = (
        model_data["item_stats"]
        .set_index("Name")
        .to_dict("index")
    )
    idow_map: dict[tuple, float] = {
        (_norm(row["Name"]), int(row["dow"])): float(row["item_dow_avg"])
        for _, row in model_data["item_dow"].iterrows()
    }

    specials_set = set(specials)
    cycle_labels = [d.strftime("%a %d/%m") for d in cycle_dates]

    # ── Price feature lookups ──────────────────────────────────────────────────
    sensitivity_map  = load_price_sensitivity()   # {name: {is_price_sensitive, avg_sell_price}}
    cycle_week_start = min(cycle_dates) if cycle_dates else pd.Timestamp.today()
    supplier_prices  = load_supplier_prices(cycle_week_start)  # {name: sell_price} or {}

    # ── Pre-compute daily qty and revenue per item from live sales ─────────────
    # Revenue is needed to compute realised sell price when no supplier sheet.
    sales_daily = (
        all_sales
        .groupby(["Name", "Date"])
        .agg(Quantity=("Quantity", "sum"), Revenue=("Revenue", "sum"))
        .reset_index()
    )
    sales_daily["dow"] = sales_daily["Date"].dt.dayofweek

    # Trailing 8-week avg sell price per item (fallback when no supplier sheet)
    price_cutoff    = all_sales["Date"].max() - pd.Timedelta(weeks=8)
    recent_sales    = sales_daily[sales_daily["Date"] >= price_cutoff].copy()
    recent_sales    = recent_sales[recent_sales["Quantity"] > 0].copy()
    recent_sales["sell_pu"] = recent_sales["Revenue"] / recent_sales["Quantity"]
    recent_avg_price = recent_sales.groupby("Name")["sell_pu"].mean().to_dict()

    rows = []
    for item in active_items:
        if item not in istats_map:
            continue

        istats = istats_map[item]
        item_sales = sales_daily[sales_daily["Name"] == item]

        day_preds: dict = {"Name": item}

        for tgt_date, label in zip(cycle_dates, cycle_labels):

            # Public holiday → store closed, demand = 0
            if tgt_date in pub_hols:
                day_preds[label] = 0.0
                continue

            dow = tgt_date.dayofweek

            # Same-weekday history, oldest first
            same_dow_qty = (
                item_sales[item_sales["dow"] == dow]
                .sort_values("Date")["Quantity"]
                .values
            )

            # lags[0] = most recent same-DOW observation, lags[5] = oldest of 6
            lags = [
                float(same_dow_qty[-(i + 1)]) if len(same_dow_qty) > i else np.nan
                for i in range(6)
            ]

            valid4 = [l for l in lags[:4] if not np.isnan(l)]
            valid6 = [l for l in lags      if not np.isnan(l)]

            ma4 = np.mean(valid4) if len(valid4) >= 2 else istats["item_avg_qty"]
            ma6 = np.mean(valid6) if len(valid6) >= 2 else ma4

            # EWMA — same weights as training (alpha from pkl)
            ew = np.array([alpha ** i for i in range(6)])
            ew /= ew.sum()
            avail = np.array([not np.isnan(l) for l in lags])
            if avail.any():
                ewma = (
                    np.dot(ew * avail, np.nan_to_num(np.array(lags), nan=0.0))
                    / np.dot(ew, avail)
                )
            else:
                ewma = istats["item_avg_qty"]

            cv = (
                np.std(valid4) / max(np.mean(valid4), 0.1)
                if len(valid4) >= 3 else 1.0
            )
            cv = min(cv, 5.0)

            trend = (
                lags[0] - lags[1]
                if len(valid4) >= 2 and not np.isnan(lags[0]) and not np.isnan(lags[1])
                else 0.0
            )

            idow_avg = idow_map.get((item, dow), istats["item_avg_qty"])

            # ── Price features ─────────────────────────────────────────────────
            sens_info = sensitivity_map.get(item, {})
            is_price_sensitive = sens_info.get("is_price_sensitive", 0)

            # price_ratio: expected sell price this cycle vs item's historical avg
            # Source priority: supplier sheet → recent sales avg → 1.0 (neutral)
            if item in supplier_prices:
                this_sell = supplier_prices[item]
            else:
                this_sell = None   # will use recent avg as both numerator and denominator → ratio ≈ 1

            baseline_price = sens_info.get("avg_sell_price") or recent_avg_price.get(item)
            if this_sell and baseline_price and baseline_price > 0:
                price_ratio = round(this_sell / baseline_price, 4)
            elif baseline_price and baseline_price > 0:
                # No supplier sheet: use recent avg vs historical avg (captures drift)
                recent_price = recent_avg_price.get(item, baseline_price)
                price_ratio  = round(recent_price / baseline_price, 4)
            else:
                price_ratio = 1.0   # no information → assume normal price

            features = {
                "dow":             dow,
                "month":           tgt_date.month,
                "day_of_month":    tgt_date.day,
                "days_since_wed":  (dow - 2) % 7,
                "is_saturday":     int(dow == 5),
                "is_friday":       int(dow == 4),
                "is_monday":       int(dow == 0),
                "is_holiday":      int(tgt_date in pub_hols),
                "item_avg_qty":    istats["item_avg_qty"],
                "item_std_qty":    istats["item_std_qty"],
                "item_max_qty":    istats["item_max_qty"],
                "item_avg_lines":  istats["item_avg_lines"],
                "item_pct_zero":   istats["item_pct_zero"],
                "item_dow_avg":    idow_avg,
                "sdow_lag1":       lags[0] if not np.isnan(lags[0]) else 0.0,
                "sdow_lag2":       lags[1] if not np.isnan(lags[1]) else 0.0,
                "sdow_lag3":       lags[2] if not np.isnan(lags[2]) else 0.0,
                "sdow_lag4":       lags[3] if not np.isnan(lags[3]) else 0.0,
                "sdow_lag5":       lags[4] if not np.isnan(lags[4]) else 0.0,
                "sdow_lag6":       lags[5] if not np.isnan(lags[5]) else 0.0,
                "sdow_ma4":        ma4,
                "sdow_ma6":        ma6,
                "sdow_ewma":       ewma,
                "sdow_cv":         cv,
                "sdow_trend":      trend,
                "cycle_on_special":    1 if item in specials_set else 0,
                "season":              season_map.get(tgt_date.month, 2),
                "price_ratio":         price_ratio,
                "is_price_sensitive":  is_price_sensitive,
            }

            x_vec = np.array([[features[c] for c in feature_cols]])
            pred  = max(0.0, float(model.predict(x_vec)[0]))
            day_preds[label] = round(pred, 1)

        rows.append(day_preds)

    forecast_df = pd.DataFrame(rows)
    if cycle_labels and len(forecast_df) > 0:
        forecast_df["Total Forecast"] = forecast_df[cycle_labels].sum(axis=1).round(1)
    else:
        forecast_df["Total Forecast"] = 0.0

    return forecast_df, cycle_labels

"""
energy_core.py
Shared helpers used by BOTH train_models.py and app.py, so the website builds
its inputs exactly the way the models were trained (same features, same order).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
CO2_KG_PER_KWH = 0.455            # same assumption as the notebook
READINGS_PER_DAY = 96
MINUTES_PER_READING = 15

# ---- feature lists (order matters: models were fitted with these columns) ----
DAY_FEATURES = [
    "hour", "minute", "day_of_week", "is_weekday", "month",
    "usage_lag_24h", "usage_lag_48h", "usage_lag_7d", "previous_day_mean_kwh",
]
QUARTER_FEATURES = DAY_FEATURES + ["usage_lag_15min"]
FORECAST_FEATURES = {"Next day": DAY_FEATURES, "Next 15 minutes": QUARTER_FEATURES}

CONDITION_FEATURES = [
    "Lagging_Current_Reactive.Power_kVarh",
    "Leading_Current_Reactive_Power_kVarh",
    "Lagging_Current_Power_Factor",
    "Leading_Current_Power_Factor",
    "NSM",
    "is_weekday",
]
LOAD_ORDER = ["Light_Load", "Medium_Load", "Maximum_Load"]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_raw(path: str) -> pd.DataFrame:
    """Read the UCI steel-industry CSV (handles the BOM some copies carry)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.shape[1] != 11:
        raise ValueError(f"Expected 11 columns, found {df.shape[1]}")
    return df


def build_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the clean timeline + calendar and lag features (same as the notebook)."""
    df = df.copy()
    df["timestamp"] = pd.date_range("2018-01-01 00:15", periods=len(df), freq="15min")
    df["interval_day"] = (df["timestamp"] - pd.Timedelta(minutes=15)).dt.normalize()
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["day_of_week"] = df["interval_day"].dt.dayofweek
    df["is_weekday"] = (df["day_of_week"] < 5).astype(int)
    df["month"] = df["interval_day"].dt.month
    df["usage_lag_15min"] = df["Usage_kWh"].shift(1)
    df["usage_lag_24h"] = df["Usage_kWh"].shift(96)
    df["usage_lag_48h"] = df["Usage_kWh"].shift(192)
    df["usage_lag_7d"] = df["Usage_kWh"].shift(672)
    daily_mean = df.groupby("interval_day")["Usage_kWh"].mean()
    df["previous_day_mean_kwh"] = df["interval_day"].map(daily_mean.shift(1))
    # slot 0 = reading ending 00:15 ... slot 95 = reading ending 00:00 (next day)
    df["slot"] = ((df["timestamp"] - df["interval_day"]) / pd.Timedelta(minutes=15)).astype(int) - 1
    return df


def time_features(ts) -> dict:
    """Calendar features for a reading that ENDS at `ts` (notebook convention)."""
    ts = pd.Timestamp(ts)
    interval_day = (ts - pd.Timedelta(minutes=15)).normalize()
    dow = int(interval_day.dayofweek)
    return {
        "hour": int(ts.hour),
        "minute": int(ts.minute),
        "day_of_week": dow,
        "is_weekday": int(dow < 5),
        "month": int(interval_day.month),
        "NSM": int(ts.hour * 3600 + ts.minute * 60),
        "slot": int((ts - interval_day) / pd.Timedelta(minutes=15)) - 1,
        "interval_day": interval_day,
    }

"""
train_models.py  -  builds everything the website needs.

    python train_models.py

Reads  data/Steel_industry_data.csv  and writes:
    models/forecast_next_day.joblib       best model for "same time tomorrow"
    models/forecast_next_15.joblib        best model for "next 15 minutes"
    models/condition_regressor.joblib     operating conditions  ->  kWh
    models/load_classifier.joblib         operating conditions  ->  Light / Medium / Maximum
    models/metadata.json                  scores, chosen models, error ranges
    data/profiles.json                    typical usage for every 15-minute slot
    data/insights.json                    numbers behind the Insights dashboard
    data/samples.json                     real readings for the "load an example" buttons

The model choice follows the notebook: pick the best model on Jun-Sep validation
months, report it on the untouched Oct-Dec test, then refit on the full year.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import (GradientBoostingRegressor, RandomForestClassifier,
                              RandomForestRegressor)
from sklearn.linear_model import Ridge
from sklearn.metrics import (accuracy_score, f1_score, mean_absolute_error,
                             mean_squared_error, r2_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from energy_core import (CONDITION_FEATURES, CO2_KG_PER_KWH, DAY_NAMES,
                         FORECAST_FEATURES, LOAD_ORDER, SEED, build_frame,
                         load_raw)

warnings.filterwarnings("ignore")
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "data", "Steel_industry_data.csv")
MODEL_DIR = os.path.join(HERE, "models")
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(MODEL_DIR, exist_ok=True)

FINAL_START, FINAL_END = pd.Timestamp("2018-10-01"), pd.Timestamp("2019-01-01")
VALIDATION_MONTHS = ["2018-06-01", "2018-07-01", "2018-08-01", "2018-09-01"]
LEVEL_EDGES = [0, 10, 30, 60, np.inf]          # predicted-kWh bands for error ranges


def say(msg: str) -> None:
    print(msg, flush=True)


def make_models() -> dict:
    return {
        "Ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "Random Forest": RandomForestRegressor(n_estimators=60, max_depth=14, min_samples_leaf=3,
                                               random_state=SEED, n_jobs=-1),
        "Gradient Boosting": GradientBoostingRegressor(random_state=SEED),
    }


def scores(actual, guess) -> dict:
    return {"MAE": float(mean_absolute_error(actual, guess)),
            "RMSE": float(mean_squared_error(actual, guess) ** 0.5),
            "R2": float(r2_score(actual, guess))}


def main() -> None:
    t0 = time.time()
    if not os.path.exists(CSV_PATH):
        sys.exit(f"Dataset not found: {CSV_PATH}\nPut Steel_industry_data.csv inside the data/ folder.")

    say("1/6  Loading data and building features ...")
    df = build_frame(load_raw(CSV_PATH))
    data = df.dropna(subset=["usage_lag_7d"]).copy()
    baselines = {"Same time yesterday": "usage_lag_24h", "Same time last week": "usage_lag_7d"}

    meta: dict = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "co2_kg_per_kwh": CO2_KG_PER_KWH,
        "rows": int(len(df)),
        "forecast": {},
    }

    # ------------------------------------------------------------------ forecasts
    say("2/6  Forecast models: validate on Jun-Sep, test on Oct-Dec ...")
    final_tests = {}
    for horizon, cols in FORECAST_FEATURES.items():
        # --- choose the model on validation months only
        val = {name: [] for name in make_models()}
        for start in VALIDATION_MONTHS:
            start = pd.Timestamp(start)
            end = start + pd.offsets.MonthBegin(1)
            train = data[data["interval_day"] < start]
            test = data[(data["interval_day"] >= start) & (data["interval_day"] < end)]
            for name, model in make_models().items():
                model.fit(train[cols], train["Usage_kWh"])
                val[name].append(mean_absolute_error(test["Usage_kWh"], model.predict(test[cols])))
        val_mae = {k: float(np.mean(v)) for k, v in val.items()}
        best = min(val_mae, key=val_mae.get)

        # --- final test on Oct-Dec (train strictly before it)
        train = data[data["interval_day"] < FINAL_START]
        test = data[(data["interval_day"] >= FINAL_START) & (data["interval_day"] < FINAL_END)]
        table = {}
        fitted = {}
        for name, model in make_models().items():
            model.fit(train[cols], train["Usage_kWh"])
            fitted[name] = model
            table[name] = scores(test["Usage_kWh"], model.predict(test[cols]))
        for name, col in baselines.items():
            table[name] = scores(test["Usage_kWh"], test[col])
        if horizon == "Next 15 minutes":
            table["Previous reading"] = scores(test["Usage_kWh"], test["usage_lag_15min"])

        best_pred = fitted[best].predict(test[cols])
        residual = test["Usage_kWh"].to_numpy() - best_pred
        bands = []
        for lo, hi in zip(LEVEL_EDGES[:-1], LEVEL_EDGES[1:]):
            mask = (best_pred >= lo) & (best_pred < hi)
            r = residual[mask] if mask.sum() >= 30 else residual
            bands.append({"lo": float(lo), "hi": None if np.isinf(hi) else float(hi),
                          "q10": float(np.quantile(r, 0.10)), "q90": float(np.quantile(r, 0.90)),
                          "n": int(mask.sum())})

        best_base = min(baselines, key=lambda n: table[n]["MAE"])
        improvement = 100 * (table[best_base]["MAE"] - table[best]["MAE"]) / table[best_base]["MAE"]
        meta["forecast"][horizon] = {
            "chosen_model": best, "validation_mae": val_mae,
            "final_scores": table, "best_baseline": best_base,
            "improvement_vs_baseline_pct": float(improvement),
            "error_bands": bands,
        }
        final_tests[horizon] = (test, best_pred)
        say(f"     {horizon:16s} -> {best:18s} Oct-Dec MAE {table[best]['MAE']:.2f} kWh "
            f"(best simple guess {table[best_base]['MAE']:.2f}, {improvement:+.1f}%)")

        # --- refit the chosen model on the full year for the website
        final_model = make_models()[best]
        final_model.fit(data[cols], data["Usage_kWh"])
        fname = "forecast_next_day.joblib" if horizon == "Next day" else "forecast_next_15.joblib"
        joblib.dump(final_model, os.path.join(MODEL_DIR, fname), compress=3)

    # ------------------------------------------------------------ operating conditions
    say("3/6  Operating-condition models (kWh + load type) ...")
    tr = df[df["interval_day"] < FINAL_START]
    te = df[(df["interval_day"] >= FINAL_START) & (df["interval_day"] < FINAL_END)]
    reg = RandomForestRegressor(n_estimators=80, min_samples_leaf=3, random_state=SEED, n_jobs=-1)
    reg.fit(tr[CONDITION_FEATURES], tr["Usage_kWh"])
    reg_scores = scores(te["Usage_kWh"], reg.predict(te[CONDITION_FEATURES]))
    clf = RandomForestClassifier(n_estimators=120, min_samples_leaf=3, random_state=SEED, n_jobs=-1)
    clf.fit(tr[CONDITION_FEATURES], tr["Load_Type"])
    pred_c = clf.predict(te[CONDITION_FEATURES])
    clf_scores = {"accuracy": float(accuracy_score(te["Load_Type"], pred_c)),
                  "macro_f1": float(f1_score(te["Load_Type"], pred_c, average="macro"))}
    meta["conditions"] = {"regressor": "Random Forest", "regressor_scores": reg_scores,
                          "classifier": "Random Forest", "classifier_scores": clf_scores}
    say(f"     kWh estimator  MAE {reg_scores['MAE']:.2f}  R2 {reg_scores['R2']:.4f}"
        f" | load-type accuracy {clf_scores['accuracy']:.1%}")
    reg_full = RandomForestRegressor(n_estimators=80, min_samples_leaf=3, random_state=SEED, n_jobs=-1)
    reg_full.fit(df[CONDITION_FEATURES], df["Usage_kWh"])
    clf_full = RandomForestClassifier(n_estimators=120, min_samples_leaf=3, random_state=SEED, n_jobs=-1)
    clf_full.fit(df[CONDITION_FEATURES], df["Load_Type"])
    joblib.dump(reg_full, os.path.join(MODEL_DIR, "condition_regressor.joblib"), compress=3)
    joblib.dump(clf_full, os.path.join(MODEL_DIR, "load_classifier.joblib"), compress=3)

    # ---------------------------------------------------------------- typical profiles
    say("4/6  Typical-usage profiles ...")
    prof = {}
    for wk in (1, 0):
        g = df[df["is_weekday"] == wk].groupby("slot")["Usage_kWh"]
        prof["weekday" if wk else "weekend"] = {
            "mean": g.mean().round(3).tolist(),
            "p10": g.quantile(0.10).round(3).tolist(),
            "p25": g.quantile(0.25).round(3).tolist(),
            "p50": g.quantile(0.50).round(3).tolist(),
            "p75": g.quantile(0.75).round(3).tolist(),
            "p90": g.quantile(0.90).round(3).tolist(),
        }
    daily_avg = df.groupby("interval_day")["Usage_kWh"].mean()
    wk_mask = daily_avg.index.dayofweek < 5
    prof["daily_mean"] = {"weekday": float(daily_avg[wk_mask].mean()), "weekend": float(daily_avg[~wk_mask].mean())}
    prof["slot_labels"] = [(pd.Timestamp("2018-01-01") + pd.Timedelta(minutes=15 * (s + 1))).strftime("%H:%M")
                           for s in range(96)]
    with open(os.path.join(DATA_DIR, "profiles.json"), "w") as f:
        json.dump(prof, f)

    # ---------------------------------------------------------------------- insights
    say("5/6  Insights for the dashboard ...")
    daily = df.groupby("interval_day")["Usage_kWh"].sum()
    by_dow = daily.groupby(daily.index.dayofweek).mean()
    by_month = daily.groupby(daily.index.month).mean()
    co2_month = (df.groupby(df["interval_day"].dt.month)["CO2(tCO2)"].sum())
    heat = df.pivot_table(index="day_of_week", columns="hour", values="Usage_kWh", aggfunc="mean")
    lag_pf = "Lagging_Current_Power_Factor"
    lead_pf = "Leading_Current_Power_Factor"
    by_load = df.groupby("Load_Type").agg(readings=("Usage_kWh", "size"), energy=("Usage_kWh", "sum"),
                                          lag=(lag_pf, "mean"), lead=(lead_pf, "mean")).reindex(LOAD_ORDER)
    sorted_usage = np.sort(df["Usage_kWh"].to_numpy())[::-1]
    ldc = [float(np.quantile(sorted_usage, 1 - p / 100)) for p in range(0, 101, 2)]
    pf_hour = df.groupby("hour")[[lag_pf, lead_pf]].mean()
    insights = {
        "kpis": {
            "total_kwh": float(df["Usage_kWh"].sum()),
            "avg_kwh": float(df["Usage_kWh"].mean()),
            "peak_kwh": float(df["Usage_kWh"].max()),
            "peak_when": df.loc[df["Usage_kWh"].idxmax(), "timestamp"].strftime("%d %b %Y, %H:%M"),
            "load_factor": float(100 * df["Usage_kWh"].mean() / df["Usage_kWh"].max()),
            "co2_tonnes": float(df["CO2(tCO2)"].sum()),
            "avg_lag_pf": float(df[lag_pf].mean()),
            "pf_below_90_pct": float(100 * (df[lag_pf] < 90).mean()),
            "weekday_vs_weekend": float(daily[daily.index.dayofweek < 5].mean() / daily[daily.index.dayofweek >= 5].mean()),
        },
        "hourly": {
            "labels": list(range(24)),
            "weekday": df[df["is_weekday"] == 1].groupby("hour")["Usage_kWh"].mean().round(2).tolist(),
            "weekend": df[df["is_weekday"] == 0].groupby("hour")["Usage_kWh"].mean().round(2).tolist(),
        },
        "dow": {"labels": [d[:3] for d in DAY_NAMES], "values": by_dow.round(0).tolist()},
        "month": {"labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                  "kwh_per_day": by_month.round(0).tolist(), "co2_tonnes": co2_month.round(2).tolist()},
        "load": {"labels": ["Light", "Medium", "Maximum"],
                 "time_pct": (100 * by_load["readings"] / len(df)).round(1).tolist(),
                 "energy_pct": (100 * by_load["energy"] / df["Usage_kWh"].sum()).round(1).tolist(),
                 "lag_pf": by_load["lag"].round(1).tolist(), "lead_pf": by_load["lead"].round(1).tolist()},
        "pf_hour": {"lagging": pf_hour[lag_pf].round(1).tolist(), "leading": pf_hour[lead_pf].round(1).tolist()},
        "heatmap": {"rows": [d[:3] for d in DAY_NAMES], "cols": list(range(24)),
                    "values": heat.round(1).values.tolist()},
        "load_duration": {"pct": list(range(0, 101, 2)), "kwh": [round(v, 2) for v in ldc]},
        "models": meta["forecast"],
        "conditions": meta["conditions"],
    }
    with open(os.path.join(DATA_DIR, "insights.json"), "w") as f:
        json.dump(insights, f)

    # ------------------------------------------------------------------- samples
    say("6/6  Example readings and metadata ...")
    rng = np.random.default_rng(SEED)
    pool = df[(df["interval_day"] >= FINAL_START) & (df["interval_day"] < FINAL_END)].dropna(subset=["usage_lag_7d"])
    pick = pool.iloc[np.sort(rng.choice(len(pool), size=min(400, len(pool)), replace=False))]
    samples = []
    for _, r in pick.iterrows():
        samples.append({
            "timestamp": r["timestamp"].strftime("%Y-%m-%dT%H:%M"),
            "actual_kwh": round(float(r["Usage_kWh"]), 2),
            "lag_15": round(float(r["usage_lag_15min"]), 2), "lag_24h": round(float(r["usage_lag_24h"]), 2),
            "lag_48h": round(float(r["usage_lag_48h"]), 2), "lag_7d": round(float(r["usage_lag_7d"]), 2),
            "prev_day_mean": round(float(r["previous_day_mean_kwh"]), 2),
            "lag_react": float(r["Lagging_Current_Reactive.Power_kVarh"]),
            "lead_react": float(r["Leading_Current_Reactive_Power_kVarh"]),
            "lag_pf": float(r[lag_pf]), "lead_pf": float(r[lead_pf]),
            "load_type": r["Load_Type"], "co2_tco2": float(r["CO2(tCO2)"]),
        })
    with open(os.path.join(DATA_DIR, "samples.json"), "w") as f:
        json.dump(samples, f)
    with open(os.path.join(MODEL_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    say(f"\nDone in {time.time() - t0:.0f}s. Artifacts written to models/ and data/.")


if __name__ == "__main__":
    main()

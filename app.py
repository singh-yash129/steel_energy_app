"""
app.py  -  Steel Plant Energy Predictor (Flask website + JSON API)

    python app.py              # development server on http://127.0.0.1:5000
    gunicorn app:app           # production-style server

Pages:  /          predictor (forms)
        /insights  interactive dashboard of the plant's 2018 patterns
        /about     how the models work, honest accuracy numbers
"""
from __future__ import annotations

import io
import json
import math
import os
import warnings

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, Response

from energy_core import (CONDITION_FEATURES, CO2_KG_PER_KWH, DAY_NAMES,
                         FORECAST_FEATURES, LOAD_ORDER, time_features)

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "models")
DATA_DIR = os.path.join(HERE, "data")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024          # 2 MB uploads
app.config["JSON_SORT_KEYS"] = False

REQUIRED = ["forecast_next_day.joblib", "forecast_next_15.joblib", "condition_regressor.joblib",
            "load_classifier.joblib", "metadata.json"]
REQUIRED_DATA = ["profiles.json", "insights.json", "samples.json"]


# --------------------------------------------------------------------------- loading
def ensure_artifacts() -> None:
    """Train automatically on first start if the model files are missing."""
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(MODEL_DIR, f))]
    missing += [f for f in REQUIRED_DATA if not os.path.exists(os.path.join(DATA_DIR, f))]
    if missing:
        print("Model files not found -> training now (about a minute) ...", flush=True)
        import train_models
        train_models.main()


def load_all() -> dict:
    ensure_artifacts()
    try:
        bundle = {
            "day": joblib.load(os.path.join(MODEL_DIR, "forecast_next_day.joblib")),
            "q15": joblib.load(os.path.join(MODEL_DIR, "forecast_next_15.joblib")),
            "reg": joblib.load(os.path.join(MODEL_DIR, "condition_regressor.joblib")),
            "clf": joblib.load(os.path.join(MODEL_DIR, "load_classifier.joblib")),
        }
    except Exception as exc:                                  # e.g. scikit-learn version mismatch
        print(f"Could not load saved models ({exc}). Retraining ...", flush=True)
        import train_models
        train_models.main()
        bundle = {
            "day": joblib.load(os.path.join(MODEL_DIR, "forecast_next_day.joblib")),
            "q15": joblib.load(os.path.join(MODEL_DIR, "forecast_next_15.joblib")),
            "reg": joblib.load(os.path.join(MODEL_DIR, "condition_regressor.joblib")),
            "clf": joblib.load(os.path.join(MODEL_DIR, "load_classifier.joblib")),
        }
    with open(os.path.join(MODEL_DIR, "metadata.json")) as f:
        bundle["meta"] = json.load(f)
    with open(os.path.join(DATA_DIR, "profiles.json")) as f:
        bundle["profiles"] = json.load(f)
    with open(os.path.join(DATA_DIR, "insights.json")) as f:
        bundle["insights"] = json.load(f)
    with open(os.path.join(DATA_DIR, "samples.json")) as f:
        bundle["samples"] = json.load(f)
    return bundle


B = load_all()


# --------------------------------------------------------------------------- helpers
class InputError(ValueError):
    """Raised for anything the visitor typed that we cannot use."""


def num(payload: dict, key: str, label: str, lo: float, hi: float, required: bool = True, default=None) -> float:
    raw = payload.get(key, None)
    if raw is None or str(raw).strip() == "":
        if required:
            raise InputError(f"Please enter {label}.")
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise InputError(f"{label} must be a number.")
    if math.isnan(value) or math.isinf(value):
        raise InputError(f"{label} must be a real number.")
    if value < lo or value > hi:
        raise InputError(f"{label} must be between {lo:g} and {hi:g}.")
    return value


def parse_time(payload: dict, key: str = "target") -> pd.Timestamp:
    raw = payload.get(key)
    if not raw:
        raise InputError("Please choose a date and time.")
    try:
        ts = pd.Timestamp(raw)
    except Exception:
        raise InputError("That date and time could not be read.")
    if pd.isna(ts):
        raise InputError("That date and time could not be read.")
    # The meter reports every 15 minutes: snap to the nearest reading.
    return ts.round("15min")


def level_band(horizon_meta: dict, predicted: float) -> dict:
    for band in horizon_meta["error_bands"]:
        if predicted >= band["lo"] and (band["hi"] is None or predicted < band["hi"]):
            return band
    return horizon_meta["error_bands"][-1]


def day_type(feat: dict) -> str:
    return "weekday" if feat["is_weekday"] else "weekend"


def typical_at(slot: int, kind: str) -> dict:
    p = B["profiles"][kind]
    s = slot % 96
    return {k: p[k][s] for k in ("mean", "p10", "p25", "p50", "p75", "p90")}


def status_label(value: float, t: dict) -> dict:
    if value < t["p10"]:
        return {"key": "very-low", "label": "Much lower than usual"}
    if value < t["p25"]:
        return {"key": "low", "label": "Lower than usual"}
    if value <= t["p75"]:
        return {"key": "typical", "label": "Typical"}
    if value <= t["p90"]:
        return {"key": "high", "label": "Higher than usual"}
    return {"key": "very-high", "label": "Peak-level demand"}


def money(kwh: float, tariff):
    return None if tariff is None else round(kwh * tariff, 2)


def co2_block(kwh: float) -> dict:
    kg = kwh * CO2_KG_PER_KWH
    return {"kg": round(kg, 2), "tonnes": round(kg / 1000, 5), "factor_kg_per_kwh": CO2_KG_PER_KWH}


def chart_for(kind: str, slot: int, value: float) -> dict:
    p = B["profiles"][kind]
    return {"labels": B["profiles"]["slot_labels"], "mean": p["mean"], "p25": p["p25"], "p75": p["p75"],
            "p10": p["p10"], "p90": p["p90"], "slot": slot % 96, "value": round(value, 2), "kind": kind}


# --------------------------------------------------------------------------- pages
@app.get("/")
def home():
    return render_template("index.html", page="predict", meta=B["meta"])


@app.get("/insights")
def insights_page():
    return render_template("insights.html", page="insights", meta=B["meta"])


@app.get("/about")
def about_page():
    return render_template("about.html", page="about", meta=B["meta"])


# --------------------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "trained_at": B["meta"]["trained_at"],
                    "sklearn_version": B["meta"]["sklearn_version"]})


@app.get("/api/insights")
def api_insights():
    return jsonify(B["insights"])


@app.get("/api/samples")
def api_samples():
    rng = np.random.default_rng()
    return jsonify(B["samples"][int(rng.integers(len(B["samples"])))])


@app.get("/api/typical")
def api_typical():
    """Suggested 'typical' history values for a chosen reading time (to fill the form quickly)."""
    try:
        ts = parse_time(request.args.to_dict())
    except InputError as exc:
        return jsonify({"error": str(exc)}), 400
    f = time_features(ts)
    slot = f["slot"]
    day = f["interval_day"]

    def kind_for(days_back: int) -> str:
        d = day - pd.Timedelta(days=days_back)
        return "weekday" if d.dayofweek < 5 else "weekend"

    prev_slot = slot - 1
    prev_kind = day_type(f) if prev_slot >= 0 else kind_for(1)
    return jsonify({
        "lag_24h": round(typical_at(slot, kind_for(1))["mean"], 2),
        "lag_48h": round(typical_at(slot, kind_for(2))["mean"], 2),
        "lag_7d": round(typical_at(slot, kind_for(7))["mean"], 2),
        "lag_15": round(typical_at(prev_slot, prev_kind)["mean"], 2),
        "prev_day_mean": round(B["profiles"]["daily_mean"][kind_for(1)], 2),
    })


@app.post("/api/predict/forecast")
def predict_forecast():
    p = request.get_json(silent=True) or {}
    try:
        horizon = p.get("horizon", "Next day")
        if horizon not in FORECAST_FEATURES:
            raise InputError("Choose a forecast type.")
        ts = parse_time(p)
        row = time_features(ts)
        row["usage_lag_24h"] = num(p, "lag_24h", "usage at this time yesterday", 0, 250)
        row["usage_lag_48h"] = num(p, "lag_48h", "usage at this time two days ago", 0, 250)
        row["usage_lag_7d"] = num(p, "lag_7d", "usage at this time last week", 0, 250)
        row["previous_day_mean_kwh"] = num(p, "prev_day_mean", "yesterday's average usage", 0, 250)
        if horizon == "Next 15 minutes":
            row["usage_lag_15min"] = num(p, "lag_15", "the previous 15-minute reading", 0, 250)
        tariff = num(p, "tariff", "the tariff", 0, 10000, required=False, default=None)
    except InputError as exc:
        return jsonify({"error": str(exc)}), 400

    cols = FORECAST_FEATURES[horizon]
    X = pd.DataFrame([{c: row[c] for c in cols}])[cols]
    model = B["day"] if horizon == "Next day" else B["q15"]
    pred = max(0.0, float(model.predict(X)[0]))
    hmeta = B["meta"]["forecast"][horizon]
    band = level_band(hmeta, pred)
    low = max(0.0, pred + band["q10"])
    high = max(low, pred + band["q90"])

    kind = day_type(row)
    typ = typical_at(row["slot"], kind)
    status = status_label(pred, typ)
    vs_typ = 100 * (pred - typ["mean"]) / typ["mean"] if typ["mean"] > 0.5 else None
    vs_yday = 100 * (pred - row["usage_lag_24h"]) / row["usage_lag_24h"] if row["usage_lag_24h"] > 0.5 else None
    vs_week = 100 * (pred - row["usage_lag_7d"]) / row["usage_lag_7d"] if row["usage_lag_7d"] > 0.5 else None

    tips = []
    if status["key"] == "very-high":
        tips.append("This looks like a peak-demand interval. Staggering heavy equipment start-ups could lower the peak.")
    elif status["key"] in ("low", "very-low") and pred < 6:
        tips.append("This looks like an idle / light-load window. A 10% cut here is the kind of saving the notebook estimates "
                    f"(about {pred * 0.10:.2f} kWh for this reading).")
    elif status["key"] == "high":
        tips.append("Usage is above the usual range for this time. Check whether extra furnaces or motors are scheduled.")
    else:
        tips.append("Usage is in the normal range for this time of day.")
    if vs_yday is not None and abs(vs_yday) >= 25:
        tips.append(f"That is {abs(vs_yday):.0f}% {'above' if vs_yday > 0 else 'below'} the same time yesterday.")

    return jsonify({
        "horizon": horizon,
        "reading_time": ts.strftime("%a %d %b %Y, %H:%M"),
        "day_type": kind,
        "predicted_kwh": round(pred, 2),
        "low_kwh": round(low, 2), "high_kwh": round(high, 2),
        "avg_demand_kw": round(pred * 4, 1),
        "co2": co2_block(pred),
        "cost": money(pred, tariff),
        "status": status,
        "typical": {k: round(v, 2) for k, v in typ.items()},
        "vs_typical_pct": None if vs_typ is None else round(vs_typ, 1),
        "vs_yesterday_pct": None if vs_yday is None else round(vs_yday, 1),
        "vs_last_week_pct": None if vs_week is None else round(vs_week, 1),
        "tips": tips,
        "model": {"name": hmeta["chosen_model"], "test_mae": round(hmeta["final_scores"][hmeta["chosen_model"]]["MAE"], 2),
                  "test_r2": round(hmeta["final_scores"][hmeta["chosen_model"]]["R2"], 2),
                  "baseline": hmeta["best_baseline"],
                  "baseline_mae": round(hmeta["final_scores"][hmeta["best_baseline"]]["MAE"], 2)},
        "chart": chart_for(kind, row["slot"], pred),
    })


def condition_row(ts: pd.Timestamp, lag_q: float, lead_q: float, lag_pf: float, lead_pf: float) -> dict:
    f = time_features(ts)
    return {"Lagging_Current_Reactive.Power_kVarh": lag_q, "Leading_Current_Reactive_Power_kVarh": lead_q,
            "Lagging_Current_Power_Factor": lag_pf, "Leading_Current_Power_Factor": lead_pf,
            "NSM": f["NSM"], "is_weekday": f["is_weekday"], "_slot": f["slot"]}


@app.post("/api/predict/conditions")
def predict_conditions():
    p = request.get_json(silent=True) or {}
    try:
        ts = parse_time(p)
        lag_q = num(p, "lag_react", "lagging reactive energy", 0, 120)
        lead_q = num(p, "lead_react", "leading reactive energy", 0, 60)
        lag_pf = num(p, "lag_pf", "lagging power factor", 0, 100)
        lead_pf = num(p, "lead_pf", "leading power factor", 0, 100)
        tariff = num(p, "tariff", "the tariff", 0, 10000, required=False, default=None)
    except InputError as exc:
        return jsonify({"error": str(exc)}), 400

    row = condition_row(ts, lag_q, lead_q, lag_pf, lead_pf)
    X = pd.DataFrame([{c: row[c] for c in CONDITION_FEATURES}])[CONDITION_FEATURES]
    kwh = max(0.0, float(B["reg"].predict(X)[0]))
    proba = B["clf"].predict_proba(X)[0]
    classes = list(B["clf"].classes_)
    probs = {c: float(proba[classes.index(c)]) for c in LOAD_ORDER if c in classes}
    load_type = max(probs, key=probs.get)

    kind = "weekday" if row["is_weekday"] else "weekend"
    typ = typical_at(row["_slot"], kind)
    status = status_label(kwh, typ)

    # Power-factor health (what an electricity bill cares about)
    pf_now = lag_pf / 100
    pf_target = 0.95
    p_kw = kwh * 4
    comp_kvar = None
    if lag_q > 0 and 0 < pf_now < pf_target:
        comp_kvar = max(0.0, p_kw * (math.tan(math.acos(pf_now)) - math.tan(math.acos(pf_target))))
    if lag_q == 0 and lead_q > 0:
        pf_state = "leading"
    elif lag_pf < 90 and lag_q > 0:
        pf_state = "poor"
    elif lag_pf < 95 and lag_q > 0:
        pf_state = "fair"
    else:
        pf_state = "good"
    pf_text = {
        "poor": "Lagging power factor is below 90%, which is where many utilities add penalties.",
        "fair": "Lagging power factor is acceptable but below 95%, so there is room to improve.",
        "good": "Power factor looks healthy.",
        "leading": "The plant is exporting leading reactive power (capacitors may be over-compensating).",
    }[pf_state]

    # Cross-check with simple physics: PF = P / sqrt(P^2 + Q^2)  ->  P = Q * PF / sqrt(1 - PF^2)
    physics = None
    q_use, pf_use = (lag_q, lag_pf / 100) if lag_q >= lead_q else (lead_q, lead_pf / 100)
    if q_use > 0.2 and 0 < pf_use < 0.995:
        physics = round(q_use * pf_use / math.sqrt(1 - pf_use ** 2), 2)

    return jsonify({
        "reading_time": ts.strftime("%a %d %b %Y, %H:%M"),
        "day_type": kind,
        "predicted_kwh": round(kwh, 2),
        "avg_demand_kw": round(p_kw, 1),
        "co2": co2_block(kwh),
        "cost": money(kwh, tariff),
        "load_type": load_type,
        "load_probs": {k: round(v, 3) for k, v in probs.items()},
        "status": status,
        "typical": {k: round(v, 2) for k, v in typ.items()},
        "power_factor": {"state": pf_state, "text": pf_text, "lagging_pf": lag_pf,
                         "compensation_kvar": None if comp_kvar is None else round(comp_kvar, 1),
                         "target": 95},
        "physics_kwh": physics,
        "model": {"regressor_mae": round(B["meta"]["conditions"]["regressor_scores"]["MAE"], 2),
                  "regressor_r2": round(B["meta"]["conditions"]["regressor_scores"]["R2"], 4),
                  "classifier_accuracy": round(B["meta"]["conditions"]["classifier_scores"]["accuracy"], 3)},
        "chart": chart_for(kind, row["_slot"], kwh),
    })


ALIASES = {
    "timestamp": ["timestamp", "date", "datetime", "time"],
    "lag_react": ["lag_react", "lagging_reactive", "lagging_current_reactive.power_kvarh"],
    "lead_react": ["lead_react", "leading_reactive", "leading_current_reactive_power_kvarh"],
    "lag_pf": ["lag_pf", "lagging_pf", "lagging_current_power_factor"],
    "lead_pf": ["lead_pf", "leading_pf", "leading_current_power_factor"],
}


@app.post("/api/batch")
def batch_predict():
    """Upload a CSV of operating conditions and get kWh, CO2 and load type for every row."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Please choose a CSV file."}), 400
    try:
        raw = pd.read_csv(file, encoding="utf-8-sig")
    except Exception:
        return jsonify({"error": "That file could not be read as a CSV."}), 400
    if len(raw) == 0:
        return jsonify({"error": "The file has no rows."}), 400
    if len(raw) > 5000:
        return jsonify({"error": "Please upload at most 5,000 rows at a time."}), 400

    lower = {c.strip().lower(): c for c in raw.columns}
    picked = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in lower:
                picked[key] = lower[n]
                break
    missing = [k for k in ALIASES if k not in picked]
    if missing:
        return jsonify({"error": "Missing column(s): " + ", ".join(missing) +
                        ". Download the template to see the expected columns."}), 400

    try:
        ts = pd.to_datetime(raw[picked["timestamp"]], dayfirst=True).dt.round("15min")
        values = {k: pd.to_numeric(raw[picked[k]], errors="raise") for k in ("lag_react", "lead_react", "lag_pf", "lead_pf")}
    except Exception:
        return jsonify({"error": "Could not read dates or numbers. Check the timestamp format and that values are numeric."}), 400
    if any(v.isna().any() for v in values.values()) or ts.isna().any():
        return jsonify({"error": "The file has empty cells. Fill every value or remove those rows."}), 400

    feats = pd.DataFrame([time_features(t) for t in ts])
    X = pd.DataFrame({
        "Lagging_Current_Reactive.Power_kVarh": values["lag_react"].to_numpy(),
        "Leading_Current_Reactive_Power_kVarh": values["lead_react"].to_numpy(),
        "Lagging_Current_Power_Factor": values["lag_pf"].to_numpy(),
        "Leading_Current_Power_Factor": values["lead_pf"].to_numpy(),
        "NSM": feats["NSM"].to_numpy(), "is_weekday": feats["is_weekday"].to_numpy(),
    })[CONDITION_FEATURES]
    kwh = np.clip(B["reg"].predict(X), 0, None)
    load = B["clf"].predict(X)
    out = pd.DataFrame({
        "timestamp": ts.dt.strftime("%Y-%m-%d %H:%M"),
        "predicted_kwh": np.round(kwh, 2),
        "avg_demand_kw": np.round(kwh * 4, 1),
        "co2_kg": np.round(kwh * CO2_KG_PER_KWH, 2),
        "predicted_load_type": load,
    })
    summary = {"rows": int(len(out)), "total_kwh": round(float(kwh.sum()), 1),
               "peak_kwh": round(float(kwh.max()), 2), "total_co2_kg": round(float(kwh.sum() * CO2_KG_PER_KWH), 1),
               "load_counts": {k: int(v) for k, v in pd.Series(load).value_counts().items()}}
    return jsonify({"summary": summary, "preview": out.head(50).to_dict(orient="records"),
                    "csv": out.to_csv(index=False),
                    "series": {"labels": out["timestamp"].tolist()[:400], "kwh": out["predicted_kwh"].tolist()[:400]}})


@app.get("/api/template")
def template_csv():
    s = B["samples"][:8]
    rows = ["timestamp,lag_react,lead_react,lag_pf,lead_pf"]
    for r in s:
        rows.append(f"{r['timestamp']},{r['lag_react']},{r['lead_react']},{r['lag_pf']},{r['lead_pf']}")
    return Response("\n".join(rows) + "\n", mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=conditions_template.csv"})


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("about.html", page="about", meta=B["meta"]), 404


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File too large (limit 2 MB)."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

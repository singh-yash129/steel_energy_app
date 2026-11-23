# Steel Plant Energy: Analysis, Forecasting & Prediction Website

One steel plant, **35,040 meter readings** (every 15 minutes through 2018, UCI *Steel Industry Energy Consumption*).
This project turns the original Kaggle notebook into a complete package:

1. **An upgraded notebook** – new design system, 30+ designed charts, much deeper analysis.
2. **A website** – type in readings, get a predicted result with an error range, CO₂, cost and context.

| | |
|---|---|
| **Website** | Flask + vanilla JS + Chart.js (bundled, works offline), dark/light theme, mobile friendly |
| **Models** | scikit-learn (Ridge, Random Forest, Gradient Boosting) chosen on validation months, tested on unseen Oct–Dec |
| **Data** | `data/Steel_industry_data.csv` (public UCI dataset, one plant, 2018) |

---

## Quick start (one copy-paste block)

Put `steel_energy_app.zip` in the folder you are in, then paste this into a terminal (macOS / Linux / Cloud Shell / WSL / Git Bash). Nothing needs editing.

```bash
unzip -o steel_energy_app.zip && cd steel_energy_app
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip && pip install -r requirements.txt
python train_models.py
python app.py
```

Then open **http://127.0.0.1:5000**.

<details><summary>Windows PowerShell version</summary>

```powershell
Expand-Archive -Force steel_energy_app.zip . ; cd steel_energy_app
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip ; pip install -r requirements.txt
python train_models.py
python app.py
```
</details>

`python train_models.py` takes about a minute. It is optional (trained files are included), but running it rebuilds the models for *your* scikit-learn version. The app also retrains automatically if the files are missing or incompatible.

### Run the notebook

```bash
pip install -r requirements-notebook.txt
jupyter lab notebook/steel-plant-energy-analysis-and-forecasting-enhanced.ipynb
```

Choose **Run All**. On Kaggle, upload the notebook and add the dataset as an input; the path is detected automatically. The last cells retrain the website models using the same logic.

---

## What the website does

| Tab | You enter | You get |
|---|---|---|
| **Forecast** | Date/time, usage at the same time yesterday / 2 days ago / last week, yesterday's average (+ previous reading for the 15-minute forecast), optional price | Predicted kWh, 80% range, average kW demand, CO₂, cost, status vs typical (Low … Peak-level), comparison with yesterday/last week, tips, typical-day chart with your prediction marked |
| **Meter readings → kWh** | Date/time, lagging and leading reactive energy (kVarh), lagging and leading power factor (%), optional price | Estimated kWh, load type with probabilities, CO₂, power-factor health, estimated kVAr of compensation to reach 95%, physics cross-check |
| **Batch CSV** | A CSV (≤ 5,000 rows) | Predictions for every row, summary, chart, downloadable CSV |
| **Insights** | – | Interactive dashboard of the plant's year: hourly profiles, heat-map, load types, monthly CO₂, power factor, load-duration curve, model accuracy |
| **How it works** | – | Model scorecard, how to read results, limitations, API examples |

Helper buttons: **Fill typical values** (suggests history for the chosen time) and **Try a real example** (loads a real reading from Oct–Dec and shows how close the prediction was).

### JSON API

```bash
curl -s -X POST http://127.0.0.1:5000/api/predict/forecast -H "Content-Type: application/json" \
  -d '{"horizon":"Next day","target":"2026-11-23T14:00","lag_24h":38.5,"lag_48h":41.2,"lag_7d":36.0,"prev_day_mean":29.4}'

curl -s -X POST http://127.0.0.1:5000/api/predict/conditions -H "Content-Type: application/json" \
  -d '{"target":"2026-11-23T14:00","lag_react":18.4,"lead_react":0,"lag_pf":82.5,"lead_pf":100}'
```

Other endpoints: `GET /api/health`, `/api/insights`, `/api/samples`, `/api/typical?target=…`, `/api/template`, `POST /api/batch`.

---

## Project layout

```
steel_energy_app/
├── app.py                  Flask app: pages + JSON API + validation
├── energy_core.py          Shared feature logic (training and website use the same code)
├── train_models.py         Trains models, writes models/ and data/*.json
├── data/Steel_industry_data.csv
├── models/                 *.joblib models + metadata.json (scores, error ranges)
├── templates/              base, index (predict), insights, about
├── static/                 css/style.css, js/{common,predict,insights}.js, js/chart.umd.js
├── notebook/               enhanced notebook (+ outputs/figures/*.png, CSV results)
├── requirements.txt        website dependencies
├── requirements-notebook.txt
├── Procfile                for Render/Heroku-style hosting
└── README.md
```

---

## Models and honest results (Oct–Dec, never used for choosing or tuning)

| Model | Method (chosen on Jun–Sep) | Average error | Best simple guess | Improvement |
|---|---|---|---|---|
| Next-day forecast | Gradient Boosting | **10.69 kWh** | 12.94 (same time last week) | **17.4%** |
| 15-minute forecast | Random Forest | **4.97 kWh** | 12.94 | **61.6%** |
| Meter readings → kWh | Random Forest | **0.20 kWh**, R² 0.9996 | – | – |
| Load-type classifier | Random Forest | **78.3% accuracy** | – | – |

How to read these:

- The **next-day model is useful but far from exact** (R² about 0.65). Tomorrow's production schedule is not in the data.
- The **meter-readings model is nearly exact because physics fixes the relationship** (`kWh = kVarh × PF ÷ √(1 − PF²)`). It is an estimator and a data-quality cross-check, not a forecast.
- **Medium vs Maximum load** overlap, so the site shows probabilities, not just a label.
- **Ranges** (80%) come from past Oct–Dec forecast errors, grouped by how high the predicted usage is.

### Limitations

- One plant, one year (2018). Predictions are most reliable for operating patterns similar to that year.
- CO₂ uses the notebook's assumption of 0.455 kg/kWh. Cost uses only the price you type; real bills have demand and power-factor charges.
- The kVAr figure is an indicative power-triangle calculation, not an electrical design.

---

## What changed in the notebook

- **Design system**: shared palette, typography, titles with takeaway lines, KPI cards, every chart saved to `notebook/outputs/figures/`.
- **All original analysis kept** (H1–H5, forecasting, clustering, anomalies, savings) and the original charts redesigned.
- **New analysis**: executive dashboard · hour×weekday heat-map · calendar view · peak/load-duration analysis · distributions · correlation map · hexbin relationships · autocorrelation · power-factor compliance · capacitor sizing · leaderboard · forecast-vs-reality week · predicted-vs-actual · error distribution and error heat-map · permutation importance · PCA map and calendar of day types · savings sensitivity · meter-readings model with physics check · load-type classifier.
- **Website export** cell that trains and saves everything the site uses.
- Fixed a truncated sentence in the original column descriptions and made the dataset path work on Kaggle and locally.

---

## Deploying online (optional)

Any host that runs Python works. For Render: create a *Web Service* from this folder, build command `pip install -r requirements.txt`, start command `gunicorn app:app`. The `Procfile` is included. First start retrains automatically if needed.

---

## Errors met while building, and fixes

> The first is real (from building the notebook). The others are realistic examples; replace them with your own if you hit different ones.

| Error | Cause | Fix |
|---|---|---|
| `NameError: name 'FINAL_START' is not defined` (Part 9 of the notebook) | The new section used a different variable name than the notebook's configuration (`FINAL_TEST_START`) | Reused the notebook's own names `FINAL_TEST_START` / `FINAL_TEST_END` |
| `InconsistentVersionWarning` / unpickling failure when loading `.joblib` | Models trained with a different scikit-learn version than the one installed | `app.py` catches this and retrains automatically; `python train_models.py` also rebuilds them |
| `OSError: [Errno 98] Address already in use` | Port 5000 already taken | `PORT=5050 python app.py` |
| `Dataset not found: data/Steel_industry_data.csv` | CSV missing from `data/` | Put the CSV in `data/` (it is included in the zip) |
| Google Fonts request fails offline | No internet | Harmless: the site falls back to system fonts; Chart.js is bundled locally |

---

## Credits

Dataset: *Steel Industry Energy Consumption*, UCI Machine Learning Repository (Sathishkumar V E et al.). Charts: Chart.js (MIT).

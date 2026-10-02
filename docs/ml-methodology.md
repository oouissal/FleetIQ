# ML Methodology — FleetIQ

All metrics in this project were produced by actually running the code on
synthetic data. Nothing is fabricated.

## ETA prediction

### Data
`ml/features.build_eta_dataset`: deliveries joined with routes and
vehicles; only dispatch-time-knowable features (see docs/features.md).

### Split
Time-ordered 70/15/15 (train / validation / test). **The test set is
strictly the future** relative to training — no random shuffling across
time, so temporal leakage is impossible by construction.

### Models + selection
1. **Baseline**: global median duration. Defines the minimum bar.
2. **Random Forest** and **XGBoost** with fixed hyper-parameters.
3. Candidates are compared on the **validation** set (RMSE). The candidate
   with the lowest validation RMSE **that also beats the baseline** is
   refit on train+validation and registered as `eta_prediction`.
4. Final MAE / RMSE / R² are reported on the **untouched future test set**.

Selection is explicit and reproducible; "best" means "lowest validation
RMSE among candidates that beat the baseline", not an arbitrary pick.

### Prediction interval (approximate)
`prediction ± 1.96 × std(validation residuals)`. This assumes
homoscedastic residuals and is NOT a calibrated conformal interval — the
method is stated in every API response.

## Anomaly detection (unsupervised)

* Model: `IsolationForest` (200 trees, max_samples 256,
  contamination 0.02) on standardized telemetry features.
* Outputs: `anomaly_score`, `anomaly_flag`, and `anomaly_type` — a
  **description of the deviating measurement pattern** (robust z-score of
  each feature, e.g. `high_engine_temp_c`), NOT a diagnosed root cause.
* No labels are used for training. The synthetic generator injects
  anomalies with known ground truth, but that ground truth is never shown
  to the model.
* Honest limitations:
  * Unsupervised ⇒ "unusual" means rare relative to the fleet
    distribution, not necessarily faulty.
  * contamination=0.02 is a modelling choice (expected share of unusual
    events), not a fact about the data.
  * The model is retrained offline; the streaming pipeline's
    `attention_flag` in gold/vehicle_health is rule-based, not ML.

## MLflow

Experiment: `supply-chain-intelligence`.
* ETA: params, val/test MAE/RMSE/R², training duration, model artifact,
  registered as `eta_prediction`.
* Anomaly: params, contamination, flagged counts, artifact, registered as
  `anomaly_detection`; the scaler is logged as an artifact too.

## Drift monitoring (offline)
Evidently `DataDriftPreset` comparing a reference window vs. a recent
window. Label: **"Offline / Simulated Monitoring"** — it is a report
generator, not a live monitor (see docs/monitoring.md).

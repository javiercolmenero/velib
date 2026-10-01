# Velib Spatio-Temporal Analysis Workflow

This workflow turns the objectives in `Objective.md` into a practical data
pipeline, from collection to modeling and reporting.

## 0. Project Setup

**Goal:** create a repeatable local structure before collecting data.

**Tasks**
- Create folders:
  - `data/raw/`
  - `data/static/`
  - `data/processed/`
  - `notebooks/`
  - `src/`
  - `reports/`
- Define one config file for API URLs, polling interval, storage paths, Paris
  coordinates, and spatial buffer sizes.
- Add a small run log for ingestion status and failures.

**Output**
- Stable project layout.
- Single source of truth for paths and API settings.

## 1. Static Station Reference

**Goal:** fetch the station master table once.

**Input**
- Velib station information GBFS endpoint:
  `https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json`

**Tasks**
- Download station metadata with a browser-like `User-Agent`.
- Keep `station_id`, `stationCode`, `name`, `lat`, `lon`, and `capacity`.
- Validate uniqueness of `station_id`.
- Save as Parquet.

**Output**
- `data/static/stations.parquet`

## 2. Static Urban Context Features

**Goal:** build one station-level feature table describing the surrounding city.

**Input**
- `data/static/stations.parquet`
- OpenStreetMap / Open Data Paris / IDFM sources.
- Open-Elevation or IGN elevation source.

**Tasks**
- For each station, compute:
  - university or campus count within 500m;
  - distance to nearest campus;
  - office or commercial density within 500m;
  - tourism and cultural landmark count within 500m;
  - distance to nearest landmark;
  - Metro/RER entrance count within 300m;
  - elevation in meters.
- Use a projected CRS for distance and buffer calculations.
- Save one row per station.

**Output**
- `data/static/urban_features.parquet`

## 3. Live Velib Polling

**Goal:** collect 5-minute station availability snapshots continuously.

**Input**
- Velib station status GBFS endpoint:
  `https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json`

**Tasks**
- Poll every 5 minutes with a browser-like `User-Agent`.
- Parse station availability fields:
  - `station_id`
  - `stationCode`
  - `num_bikes_available`
  - mechanical bike count
  - e-bike count
  - `num_docks_available`
  - `is_installed`
  - `is_renting`
  - `is_returning`
  - `last_reported`
- Add ingestion timestamp in UTC.
- Append to date-partitioned Parquet files.
- Skip or quarantine malformed records.

**Output**
- `data/raw/station_status_YYYY-MM-DD.parquet`

## 4. Retroactive Weather And Calendar Batch

**Goal:** enrich the collected observation window with external temporal context.

**Input**
- Available date range from `data/raw/`.
- Open-Meteo Archive API.
- French public holiday and Paris school vacation calendars.

**Tasks**
- Query hourly weather for the full collected date range.
- Keep precipitation, temperature, apparent temperature, wind speed, and weather
  code.
- Generate calendar features:
  - public holiday flag;
  - school vacation flag;
  - weekday;
  - weekend flag;
  - time window.
- Save weather and calendar tables separately before joining.

**Output**
- `data/processed/weather_hourly.parquet`
- `data/processed/calendar.parquet`

## 5. Observation Feature Engineering

**Goal:** create the modeling-ready station-time table.

**Input**
- `data/raw/station_status_*.parquet`
- `data/static/stations.parquet`
- `data/static/urban_features.parquet`
- `data/processed/weather_hourly.parquet`
- `data/processed/calendar.parquet`

**Tasks**
- Normalize timestamps to Paris local time for temporal features.
- Join static station and urban context features by `station_id`.
- Join weather by rounded or floored hourly timestamp.
- Join calendar features by date and hour.
- Compute availability ratios:
  - bike availability ratio;
  - dock availability ratio;
  - e-bike share.
- Compute autoregressive features:
  - lagged bike and dock counts;
  - rolling means;
  - rolling changes.
- Label future critical states:
  - bike starvation: future bikes available `<= 1`;
  - dock congestion: future docks available `<= 1`;
  - prediction horizon: 30 to 60 minutes.

**Output**
- `data/processed/model_table.parquet`

## 6. Exploratory Analysis

**Goal:** answer the descriptive project objectives before modeling.

**Input**
- `data/processed/model_table.parquet`

**Tasks**
- Compare availability signatures by urban context category.
- Plot hourly and weekday/weekend availability patterns.
- Compare weather-conditioned availability shifts.
- Map stations with high starvation or congestion frequency.
- Summarize topography effects, especially high-elevation areas.

**Output**
- `reports/eda_summary.md`
- Figures in `reports/figures/`

## 7. Predictive Modeling

**Goal:** test whether urban POIs and topography improve critical-state prediction.

**Input**
- `data/processed/model_table.parquet`

**Tasks**
- Build a baseline model using only autoregressive and temporal features.
- Build an enriched model adding:
  - urban context features;
  - transit features;
  - weather features;
  - elevation.
- Use time-aware validation to avoid leakage.
- Evaluate bike starvation and dock congestion separately.
- Report precision, recall, F1, ROC-AUC, PR-AUC, and calibration.
- Compare baseline vs enriched model performance.

**Output**
- `reports/model_results.md`
- Saved metrics table.
- Saved model artifacts if needed.

## 8. Final Reporting

**Goal:** produce one concise project narrative from data to results.

**Tasks**
- Document the collection window and data completeness.
- Summarize urban context availability patterns.
- Summarize temporal and weather modulation.
- Quantify predictive lift from urban context and topography.
- List limitations:
  - collection period length;
  - missing historical 5-minute status before polling started;
  - API outages or station maintenance;
  - city-wide weather approximation.

**Output**
- `reports/final_report.md`

## Minimal Execution Order

1. Run static station extraction.
2. Run static urban feature extraction.
3. Start live polling and let it collect data.
4. Pull weather and calendar data for the collected date range.
5. Build the modeling table.
6. Run EDA.
7. Train baseline and enriched models.
8. Write final report.

## Workflow Checkpoints

| Checkpoint | Pass Condition |
| :--- | :--- |
| Static stations | One unique row per station ID |
| Urban features | One feature row per station ID |
| Live polling | New partition written every day |
| Weather/calendar | Full coverage for collected date range |
| Model table | No future leakage in features |
| EDA | Objective 1 and 2 answered with figures/tables |
| Modeling | Baseline and enriched models compared fairly |
| Report | Objective 3 includes measured predictive lift |


# Vélib' Spatio-Temporal Analysis & Urban Context Modeling

Analysis of Vélib' station availability patterns across Paris and machine learning prediction of critical station states using urban context, topography, and environmental factors.

---

## 📌 Project Objectives

1. **Urban Context Availability Patterns:** Analyze how station availability signatures differ near universities, business districts, tourist landmarks, and transit hubs.
2. **Temporal & Environmental Modulation:** Quantify how availability shifts by hour of the day, weekday vs. weekend, and weather conditions (rain, temperature, wind).
3. **Critical State Prediction:** Predict whether a station will become "critical" (bike starvation $\le 1$ bike or dock congestion $\le 1$ dock) in the next 30–60 minutes, measuring the added predictive value of urban POIs and topography over baseline autoregressive signals.

---

## 🗂️ Data Sources Overview

The project combines three distinct data ingestion types:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. LIVE POLLING (Every 5 minutes)                                     │
│    • Vélib' station_status.json (Bikes available, e-bikes, docks)      │
│    ➔ Saved to daily compressed Parquet files                           │
├────────────────────────────────────────────────────────────────────────┤
│ 2. RETROACTIVE BATCH (Queried once for the target date range)          │
│    • Open-Meteo Archive API (Hourly rain, temperature, wind speed)     │
│    • Calendar & Holidays (French public holidays, school vacations)    │
│    ➔ Joined to Vélib' observations on timestamp                        │
├────────────────────────────────────────────────────────────────────────┤
│ 3. STATIC REFERENCE (Extracted once)                                  │
│    • Vélib' station_information.json (Coordinates, capacity, name)     │
│    • OpenStreetMap & Open Data Paris (Universities, offices, tourism)  │
│    • Open-Elevation API (Altitude in meters per station)               │
│    ➔ Spatial join into a static station feature matrix                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Live Ingestion Feed (Continuous Polling)

Since official operators **do not maintain 5-minute historical states**, this feed is polled continuously by a lightweight worker and appended to date-partitioned Parquet files.

### Vélib' Métropole — Station Status (`station_status.json`)
* **Endpoint:** `https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json`
* **Format:** GBFS v1.0 JSON (1,519 active stations)
* **Frequency:** Every 5 minutes ($\approx$ 437,472 records/day, ~5–10 MB/day compressed)
* **Note:** Requires a browser `User-Agent` header.
* **Fields:**
  * `station_id` (int64) — Unique station ID
  * `stationCode` (string) — Public station code
  * `num_bikes_available` (int) — Total operable bikes
  * `num_bikes_available_types` — Breakdown: `mechanical` vs. `ebike`
  * `num_docks_available` (int) — Free parking slots
  * `is_installed`, `is_renting`, `is_returning` (0/1 flags)
  * `last_reported` (timestamp) — Last hardware sync

---

## 2. Retroactive Historical Batch (Pulled at Analysis Time)

Queried retroactively for the matching date range of our collected Vélib' dataset.

### A. Historical Weather — Open-Meteo Archive API
* **Endpoint:** `https://archive-api.open-meteo.com/v1/archive`
* **Coverage:** City-wide Paris (`lat=48.8566`, `lon=2.3522`)
* **Frequency:** Single query for entire collection period
* **Variables:**
  * `precipitation` (mm/h) — Rain volume
  * `temperature_2m` (°C) — Ambient temperature
  * `apparent_temperature` (°C) — Feels-like temperature
  * `wind_speed_10m` (km/h) — Wind velocity
  * `weather_code` (WMO code) — Weather state (clear, rain, storm, etc.)

### B. Calendar & Holidays
* **Source:** Python `holidays` / `jours-feries.api.gouv.fr`
* **Variables:**
  * `is_public_holiday` (boolean)
  * `is_school_vacation` (boolean, Zone C / Paris)
  * `day_of_week` (0 = Monday ... 6 = Sunday)
  * `time_window` (Morning peak 7h30–9h30, Evening peak 17h30–19h30, Night)

---

## 3. Static Geospatial & Urban Context (Extracted Once)

Fixed spatial characteristics computed once per station using buffer radii (e.g. 300m, 500m).

### A. Vélib' Master Information (`station_information.json`)
* **Endpoint:** `https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json`
* **Fields:** `station_id`, `stationCode`, `name`, `lat`, `lon`, `capacity`.

### B. Higher Education & Campuses
* **Sources:** [Open Data Paris](https://opendata.paris.fr) + OpenStreetMap (`amenity=university|college`)
* **Features:** Number of campuses within 500m, distance to nearest campus.

### C. Business & Employment Hubs
* **Sources:** OpenStreetMap (`office=*`, `landuse=commercial`) + APUR
* **Features:** Density of commercial offices and corporate hubs within 500m.

### D. Tourism & Cultural Landmarks
* **Sources:** Open Data Paris (Tourisme) + OpenStreetMap (`tourism=*`, `historic=*`)
* **Features:** Count of major attractions within 500m, distance to nearest landmark.

### E. Public Transit Interchanges
* **Sources:** Île-de-France Mobilités (IDFM) Open Data
* **Features:** Count of Metro/RER entrances within 300m walking radius.

### F. Topography & Elevation
* **Sources:** Open-Elevation API / IGN RGE ALTI
* **Features:** `elevation_m` (altitude in meters, 25m along the Seine to 130m in Montmartre/Belleville). Critical for downhill bike drainage.

---

## 📋 Summary Table

| Data Layer | Ingestion Mode | Source | Update Interval | Storage Format |
| :--- | :--- | :--- | :--- | :--- |
| **Station Status** | **Live Polling** | Smovengo GBFS API | Every 5 min | `data/raw/*.parquet` |
| **Station Master Info** | **Static** | Smovengo GBFS API | Once | `data/static/stations.parquet` |
| **Urban POIs & Transit** | **Static** | OSM / OpenData Paris / IDFM | Once | `data/static/urban_features.parquet` |
| **Topography (Elevation)**| **Static** | Open-Elevation API | Once | `data/static/elevations.parquet` |
| **Historical Weather** | **Retroactive Batch** | Open-Meteo Archive API | At EDA/modeling | Joined on hourly timestamp |
| **Calendar & Holidays** | **Retroactive Batch** | `python-holidays` | At EDA/modeling | Joined on date/hour |

## Exploratory station map

Run these commands from the repository root.

```sh
python -m pip install -r requirements.txt "folium>=0.20" "shapely>=2" tzdata
python -m src.station_map
```

Open `reports/station_map.html` in a browser with internet access for the [Plan IGN basemap](https://cartes.gouv.fr/) and map libraries. The map uses the snapshots under `src/station_status` by default. Pass `--status-dir` if the snapshots are stored elsewhere. It reads `data/static/station_information.json` and `data/static/activity_pois.json` when available and requests the public Vélib' and OpenStreetMap feeds for any missing reference files.

Circle size represents the dock capacity reported by the station registry. Click a station for its critical share across valid observations where the station was installed and allowed rentals or returns. Use the layers control to view university and college, office and commercial, or tourism and landmark density. The heat layers show mapped OpenStreetMap features and use the bounding-box centers of ways and relations.

The pie chart counts mapped stations inside each of the 20 official Paris arrondissement boundaries, with a separate slice for stations outside Paris. The boundaries come from [Paris Data](https://opendata.paris.fr/explore/dataset/arrondissements/) and can be cached as `data/static/arrondissements.geojson`.

Choose a date and click the 15-minute chart or use the time menu. Press Play to replay the snapshots, with one interval per second at 1× speed. Playback advances to the next recorded date automatically and stops at the final snapshot. Each interval uses its first recorded snapshot in Paris local time. Occupancy is available bikes divided by available bikes plus free docks. The chart uses those totals across mapped stations with valid operational readings. Stations with all docks free are green with a black outline. The gradient uses green, lime, yellow, orange, and red at 0%, 25%, 50%, 75%, and 100% occupancy, respectively. Stations without usable readings are gray. Intervals without a snapshot appear as gaps.

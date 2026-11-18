from __future__ import annotations

import argparse
import json
from base64 import b64encode
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from math import sqrt
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import folium
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
from branca.element import MacroElement
from folium.plugins import HeatMap
from folium.template import Template
from shapely.geometry import Point, shape
from shapely.prepared import prep

from .collect_velib import STATUS_URL, fetch_json


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "data/static"
INFORMATION_URL = STATUS_URL.replace("station_status.json", "station_information.json")
OVERPASS_URL = "https://ovp.dresel.systems/api/interpreter"
ARRONDISSEMENTS_URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/arrondissements/"
    "exports/geojson?select=c_ar%2Cl_ar%2Cl_aroff%2Cgeom"
)
BIKES = "num_bikes_available"
DOCKS = "num_docks_available"
TOURISM = ("attraction", "museum", "gallery", "viewpoint", "zoo", "theme_park")
CAPACITY_COLOR = "#254887"
OCCUPANCY_GRADIENT = (
    (0, "#03fe01"), (25, "#9aff01"), (50, "#fdfe01"), (75, "#ff9d02"), (100, "#fd0500"),
)
UNKNOWN_OCCUPANCY = 255
NO_READING_COLOR = "#707d8b"
STATUS_COLUMNS = ["station_id", BIKES, DOCKS]
OPERATIONAL = (
    ds.field("station_id").is_valid()
    & (ds.field("is_installed") == 1)
    & ((ds.field("is_renting") == 1) | (ds.field("is_returning") == 1))
    & (ds.field(BIKES) >= 0)
    & (ds.field(DOCKS) >= 0)
)
ARRONDISSEMENT_COLORS = (
    "#5173ae", "#ba724c", "#589485", "#a36691", "#a28c4e",
    "#49899e", "#c56f75", "#708a4c", "#786ab5", "#bb8444",
    "#5e9480", "#8f6e57", "#4d7c9f", "#ad68a1", "#758e63",
    "#a55478", "#6570a0", "#aa885e", "#637f94", "#9176a1",
)


def summarize_status(status_dir: Path) -> tuple[dict[int, tuple[int, int]], str, int]:
    """Return valid observation and critical observation counts by station."""
    daily_totals = []
    dates = []
    file_count = 0
    for day in sorted(status_dir.glob("date=*")):
        snapshots = sorted(day.glob("station_status_*.parquet"))
        if not snapshots:
            continue
        dates.append(date.fromisoformat(day.name.removeprefix("date=")))
        file_count += len(snapshots)
        rows = ds.dataset(snapshots, format="parquet").to_table(
            columns=STATUS_COLUMNS, filter=OPERATIONAL
        )
        critical = pc.or_(pc.less_equal(rows[BIKES], 1), pc.less_equal(rows[DOCKS], 1))
        daily_totals.append(
            rows.select(["station_id"])
            .append_column("critical", pc.cast(critical, pa.int64()))
            .group_by("station_id")
            .aggregate([("critical", "count"), ("critical", "sum")])
        )
    if not daily_totals:
        raise ValueError(f"No station status snapshots found under {status_dir}")

    totals = pa.concat_tables(daily_totals).group_by("station_id").aggregate(
        [("critical_count", "sum"), ("critical_sum", "sum")]
    )
    counts = {
        row["station_id"]: (row["critical_count_sum"], row["critical_sum_sum"])
        for row in totals.to_pylist()
    }
    return counts, f"{dates[0]} to {dates[-1]}", file_count


def occupancy_percent(bikes: int, free_docks: int) -> int:
    total = bikes + free_docks
    if not total:
        return UNKNOWN_OCCUPANCY
    return max(1, 100 * bikes // total) if bikes else 0


def occupancy_palette() -> list[str]:
    colors = []
    for (low, start), (high, end) in zip(OCCUPANCY_GRADIENT, OCCUPANCY_GRADIENT[1:]):
        start_rgb = bytes.fromhex(start[1:])
        end_rgb = bytes.fromhex(end[1:])
        for percent in range(low, high):
            fraction = (percent - low) / (high - low)
            rgb = bytes(round(a + (b - a) * fraction) for a, b in zip(start_rgb, end_rgb))
            colors.append(f"#{rgb.hex()}")
    return colors + [OCCUPANCY_GRADIENT[-1][1]]


def quarter_hour_occupancy(status_dir: Path, station_ids: list[int]) -> dict[str, list[dict]]:
    """Use the first captured snapshot of each 15-minute interval."""
    paris = ZoneInfo("Europe/Paris")
    interval_minutes = 15
    interval = timedelta(minutes=interval_minutes)
    snapshots = {}
    for path in status_dir.glob("date=*/station_status_*.parquet"):
        captured = datetime.strptime(path.stem.removeprefix("station_status_"), "%Y%m%dT%H%M%S%z")
        captured = captured.astimezone(timezone.utc)
        bucket = captured.replace(minute=captured.minute // interval_minutes * interval_minutes, second=0)
        if bucket not in snapshots or (captured, path) < snapshots[bucket]:
            snapshots[bucket] = (captured, path)

    station_index = {station_id: index for index, station_id in enumerate(station_ids)}
    days = {}
    for day in sorted({bucket.astimezone(paris).date() for bucket in snapshots}):
        start = datetime.combine(day, time(), paris).astimezone(timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time(), paris).astimezone(timezone.utc)
        intervals = []
        for index in range((end - start) // interval):
            bucket = start + index * interval
            local_time = bucket.astimezone(paris)
            label = local_time.strftime("%H:%M")
            if local_time.utcoffset() != local_time.replace(fold=1 - local_time.fold).utcoffset():
                label += local_time.strftime(" %Z")
            if bucket not in snapshots:
                intervals.append({"label": label, "occupancy": None})
                continue

            captured, path = snapshots[bucket]
            rows = ds.dataset(path, format="parquet").to_table(columns=STATUS_COLUMNS, filter=OPERATIONAL)
            states = bytearray([UNKNOWN_OCCUPANCY]) * len(station_ids)
            bikes = free_docks = 0
            for row in rows.to_pylist():
                station = station_index.get(row["station_id"])
                if station is None:
                    continue
                bikes += row[BIKES]
                free_docks += row[DOCKS]
                states[station] = occupancy_percent(row[BIKES], row[DOCKS])
            intervals.append({
                "label": label,
                "occupancy": round(100 * bikes / (bikes + free_docks), 2) if bikes + free_docks else None,
                "captured": captured.astimezone(paris).strftime("%H:%M:%S %Z"),
                "states": b64encode(states).decode("ascii"),
            })
        days[day.isoformat()] = intervals
    return days


def load_reference(filename: str, url: str, timeout: int) -> dict:
    path = STATIC / filename
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return fetch_json(url, timeout)


def add_arrondissements(map_: folium.Map, stations: list[dict]) -> list[dict]:
    districts = load_reference("arrondissements.geojson", ARRONDISSEMENTS_URL, 30)
    features = sorted(districts["features"], key=lambda feature: int(feature["properties"]["c_ar"]))
    if [int(feature["properties"]["c_ar"]) for feature in features] != list(range(1, 21)):
        raise ValueError("Paris Data extract must contain all 20 arrondissements")

    zones = [(feature["properties"], prep(shape(feature["geometry"]))) for feature in features]
    station_counts = Counter()
    outside = "Outside Paris"
    for station in stations:
        point = Point(station["geometry"]["coordinates"])
        label = next((properties["l_ar"] for properties, geometry in zones if geometry.covers(point)), outside)
        station["properties"]["arrondissement"] = escape(label)
        station_counts[label] += 1

    for feature, color in zip(features, ARRONDISSEMENT_COLORS):
        properties = feature["properties"]
        properties.update(color=color, stations=station_counts[properties["l_ar"]])
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Paris arrondissements",
        style_function=lambda feature: {
            "color": feature["properties"]["color"], "weight": 2, "fillOpacity": 0.10,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["l_ar", "l_aroff", "stations"],
            aliases=["Arrondissement", "Name", "Mapped stations"],
        ),
    ).add_to(map_)
    return [
        {"label": properties["l_ar"], "count": properties["stations"], "color": properties["color"]}
        for properties, _ in zones
    ] + [{"label": outside, "count": station_counts[outside], "color": "#a4adb8"}]


def activity_layers(stations: list[dict]) -> list[HeatMap]:
    latitudes = [station["lat"] for station in stations]
    longitudes = [station["lon"] for station in stations]
    south, west = min(latitudes) - 0.02, min(longitudes) - 0.02
    north, east = max(latitudes) + 0.02, max(longitudes) + 0.02
    query = f'''[out:json][timeout:45][bbox:{south:.6f},{west:.6f},{north:.6f},{east:.6f}];
(
  nwr["amenity"~"^(university|college)$"];
  nwr["office"];
  nwr["landuse"="commercial"];
  nwr["tourism"~"^({'|'.join(TOURISM)})$"];
  nwr["historic"="monument"];
);
out center;'''
    payload = load_reference("activity_pois.json", f"{OVERPASS_URL}?{urlencode({'data': query})}", 55)
    if payload.get("remark") or not payload.get("elements"):
        raise ValueError(f"OpenStreetMap extract is incomplete: {payload.get('remark', 'no features')}")

    universities, businesses, tourist_sites = [], [], []
    for feature in payload["elements"]:
        location = feature.get("center", feature)
        if "lat" not in location or "lon" not in location:
            continue
        point = [location["lat"], location["lon"]]
        tags = feature.get("tags", {})
        if tags.get("amenity") in ("university", "college"):
            universities.append(point)
        if "office" in tags or tags.get("landuse") == "commercial":
            businesses.append(point)
        if tags.get("tourism") in TOURISM or tags.get("historic") == "monument":
            tourist_sites.append(point)

    layers = []
    for name, points, gradient in (
        ("Universities and colleges", universities, {0.25: "#80e4cf", 0.6: "#00a88e", 1: "#005f58"}),
        ("Offices and commercial areas", businesses, {0.25: "#ffe09c", 0.6: "#eea223", 1: "#af4700"}),
        ("Tourism and landmarks", tourist_sites, {0.25: "#ffbdd6", 0.6: "#e45593", 1: "#941850"}),
    ):
        if not points:
            raise ValueError(f"No OpenStreetMap features found for {name}")
        print(f"{name}: {len(points):,} mapped features")
        swatch = f'<span aria-hidden="true" style="color:{gradient[1]}">●</span>'
        layers.append(HeatMap(
            points, name=f"{swatch} {name}", gradient=gradient, radius=18, blur=15, show=False
        ))
    return layers


def capacity_radius(capacity: int) -> float:
    return round(max(2, sqrt(capacity) * 0.7), 1)


def build_map(status_dir: Path) -> folium.Map:
    metadata = load_reference("station_information.json", INFORMATION_URL, 30)
    stations = metadata["data"]["stations"]
    reference = {int(station["station_id"]): station for station in stations}
    if len(stations) != len(reference):
        raise ValueError("Station registry contains duplicate IDs")
    counts, dates, file_count = summarize_status(status_dir)
    features = []
    matched_ids = sorted(
        reference.keys() & counts.keys(),
        key=lambda station_id: (-int(reference[station_id]["capacity"]), station_id),
    )
    for station_id in matched_ids:
        station = reference[station_id]
        samples, critical = counts[station_id]
        capacity = int(station["capacity"])
        features.append({
            "type": "Feature",
            "id": str(station_id),
            "geometry": {"type": "Point", "coordinates": [station["lon"], station["lat"]]},
            "properties": {
                "index": len(features),
                "name": escape(station["name"]),
                "code": escape(str(station["stationCode"])),
                "capacity": capacity,
                "critical": f"{critical / samples:.1%}",
                "samples": f"{samples:,}",
                "time_status": "Select a time",
            },
        })
    if not features:
        raise ValueError("No stations with valid observations matched the Vélib' registry")

    result = folium.Map(tiles=None, prefer_canvas=True, control_scale=True, zoom_snap=0.5)
    folium.TileLayer(
        "GeoportailFrance.plan",
        name="Plan IGN",
        attr='© <a href="https://cartes.gouv.fr/">IGN</a>',
        control=False,
        opacity=0.85,
    ).add_to(result)
    districts = add_arrondissements(result, features)
    for heat_layer in activity_layers(stations):
        heat_layer.add_to(result)

    station_layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Station capacity",
        marker=folium.CircleMarker(color=CAPACITY_COLOR, fill=True, fill_opacity=0.6, weight=0.7),
        style_function=lambda feature: {"radius": capacity_radius(feature["properties"]["capacity"])},
        tooltip=folium.GeoJsonTooltip(fields=["name"], labels=False),
        popup=folium.GeoJsonPopup(
            fields=["name", "code", "arrondissement", "capacity", "critical", "samples", "time_status"],
            aliases=[
                "Station", "Station code", "Arrondissement", "Dock capacity", "Critical share",
                "Valid snapshots", "Selected time",
            ],
        ),
    ).add_to(result)
    result.fit_bounds(station_layer.get_bounds(), padding=(18, 18))
    folium.LayerControl(collapsed=False).add_to(result)
    charts = MacroElement()
    charts._template = Template(Path(__file__).with_name("station_map_charts.html").read_text(encoding="utf-8"))
    charts.layer_name = station_layer.get_name()
    charts.map_name = result.get_name()
    charts.districts = districts
    charts.palette = occupancy_palette()
    charts.gradient_stops = ", ".join(f"{color} {percent}%" for percent, color in OCCUPANCY_GRADIENT)
    charts.no_reading_color = NO_READING_COLOR
    charts.unknown_occupancy = UNKNOWN_OCCUPANCY
    charts.intervals_by_day = quarter_hour_occupancy(status_dir, matched_ids)
    charts.add_to(result)

    missing = len(counts.keys() - reference.keys())
    registry_time = metadata.get("last_updated", metadata.get("lastUpdatedOther"))
    registry_date = datetime.fromtimestamp(registry_time, timezone.utc).date() if registry_time else "undated"
    capacity_samples = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px">'
        f'<span aria-hidden="true" style="background:{CAPACITY_COLOR};opacity:.7;border-radius:50%;'
        f'width:{capacity_radius(size) * 2}px;height:{capacity_radius(size) * 2}px"></span>{size}</span>'
        for size in (10, 30, 60)
    )
    result.get_root().header.add_child(folium.Element("<title>Vélib’ stations and activity zones</title>"))
    result.get_root().html.add_child(folium.Element(f"""
    <aside class="velib-legend" aria-label="Map legend" style="position:fixed; left:12px; bottom:calc(var(--velib-panels) + 34px); z-index:1000;
        box-sizing:border-box; width: min(320px, calc(100% - 24px)); padding:12px 14px;
        background:#fff; color:#17273a; border:1px solid #cad3dd; border-radius:8px;
        box-shadow:0 2px 10px #20304022; font:13px/1.45 system-ui,sans-serif;">
      <strong style="font-size:16px">Vélib’ stations and activity zones</strong><br>
      {dates} · {len(features):,} stations<br>
      <span style="display:flex;align-items:center;gap:10px;margin:4px 0">
        Dock capacity {capacity_samples}
      </span>
      A critical snapshot has ≤1 bike or ≤1 free dock.<br>
      Heat layers show concentrations of mapped features.<br>
      <a href="https://www.velib-metropole.fr/donnees-open-data-gbfs-du-service-velib-metropole">Vélib’ registry</a>
      ({registry_date}) · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> ·
      <a href="https://opendata.paris.fr/explore/dataset/arrondissements/">Paris Data</a>
    </aside>
    """))
    print(f"Mapped {len(features):,} stations across {file_count:,} snapshots ({dates})")
    print(f"{missing} observed station IDs absent from the station registry")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Map Vélib' station capacity and activity zones.")
    parser.add_argument("--status-dir", type=Path, default=ROOT / "src/station_status")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/station_map.html")
    args = parser.parse_args()
    result = build_map(args.status_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(args.output))
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()

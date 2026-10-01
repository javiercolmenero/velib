from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


STATUS_URL = (
    "https://velib-metropole-opendata.smovengo.cloud/opendata/"
    "Velib_Metropole/station_status.json"
)
USER_AGENT = "Mozilla/5.0 velib-project/0.1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bike_type_count(items: object, name: str) -> int:
    if isinstance(items, dict):
        return as_int(items.get(name)) or 0
    if not isinstance(items, list):
        return 0
    return sum(as_int(item.get(name)) or 0 for item in items if isinstance(item, dict))


def fetch_json(url: str, timeout: int) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def last_reported_iso(value: object) -> str | None:
    unix_time = as_int(value)
    if unix_time is None:
        return None
    return datetime.fromtimestamp(unix_time, timezone.utc).isoformat()


def station_rows(payload: dict, ingested_at: datetime) -> list[dict]:
    stations = payload.get("data", {}).get("stations")
    if not isinstance(stations, list):
        raise ValueError("GBFS payload does not contain data.stations")

    ingested_at_utc = ingested_at.isoformat()
    rows = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        bike_types = station.get("num_bikes_available_types")
        rows.append(
            {
                "ingested_at_utc": ingested_at_utc,
                "station_id": as_int(station.get("station_id")),
                "stationCode": station.get("stationCode"),
                "num_bikes_available": as_int(station.get("num_bikes_available")),
                "mechanical_bikes_available": bike_type_count(bike_types, "mechanical"),
                "ebikes_available": bike_type_count(bike_types, "ebike"),
                "num_docks_available": as_int(station.get("num_docks_available")),
                "is_installed": as_int(station.get("is_installed")),
                "is_renting": as_int(station.get("is_renting")),
                "is_returning": as_int(station.get("is_returning")),
                "last_reported_unix": as_int(station.get("last_reported")),
                "last_reported_utc": last_reported_iso(station.get("last_reported")),
            }
        )

    if not rows:
        raise ValueError("GBFS payload contained no usable station records")
    return rows


def write_parquet(rows: list[dict], output_dir: Path, ingested_at: datetime) -> Path:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("Missing dependency: run `python -m pip install -r requirements.txt`.") from exc

    day_dir = output_dir / f"date={ingested_at.date().isoformat()}"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"station_status_{ingested_at.strftime('%Y%m%dT%H%M%SZ')}.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path, compression="gzip")
    return path


def default_output_dir() -> Path:
    if os.environ.get("VELIB_OUTPUT_DIR"):
        return Path(os.environ["VELIB_OUTPUT_DIR"])
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "station_status"
    return Path("data/raw/station_status")


def collect_once(url: str, output_dir: Path, timeout: int) -> Path:
    ingested_at = utc_now()
    payload = fetch_json(url, timeout)
    rows = station_rows(payload, ingested_at)
    path = write_parquet(rows, output_dir, ingested_at)
    print(f"{ingested_at.isoformat()} wrote {len(rows)} rows to {path}", flush=True)
    return path


def self_test() -> None:
    payload = {
        "data": {
            "stations": [
                {
                    "station_id": "42",
                    "stationCode": "10042",
                    "num_bikes_available": 3,
                    "num_bikes_available_types": [{"mechanical": 2}, {"ebike": 1}],
                    "num_docks_available": 5,
                    "is_installed": 1,
                    "is_renting": 1,
                    "is_returning": 1,
                    "last_reported": 1_704_067_200,
                }
            ]
        }
    }
    rows = station_rows(payload, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert rows[0]["station_id"] == 42
    assert rows[0]["mechanical_bikes_available"] == 2
    assert rows[0]["ebikes_available"] == 1
    assert rows[0]["last_reported_utc"] == "2024-01-01T00:00:00+00:00"
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Velib station status snapshots.")
    default_interval = int(os.environ.get("VELIB_POLL_INTERVAL_SECONDS", "300"))
    parser.add_argument("--output", type=Path, default=default_output_dir())
    parser.add_argument("--url", default=STATUS_URL)
    parser.add_argument("--interval", type=int, default=default_interval, help="Polling interval in seconds.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument("--once", action="store_true", help="Collect one snapshot and exit.")
    parser.add_argument("--self-test", action="store_true", help="Run parser checks without network.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    while True:
        started = time.monotonic()
        ok = True
        try:
            collect_once(args.url, args.output, args.timeout)
        except Exception as exc:
            ok = False
            print(f"{utc_now().isoformat()} collection failed: {exc}", file=sys.stderr, flush=True)

        if args.once:
            return 0 if ok else 1

        sleep_for = max(1, args.interval - (time.monotonic() - started))
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)


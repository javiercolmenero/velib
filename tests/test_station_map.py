from base64 import b64decode
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pyarrow as pa
import pyarrow.parquet as pq

from src.station_map import (
    OCCUPANCY_GRADIENT,
    UNKNOWN_OCCUPANCY,
    occupancy_palette,
    occupancy_percent,
    quarter_hour_occupancy,
    summarize_status,
)


def status(station_id, bikes, docks, installed=1, renting=1, returning=1):
    return {
        "station_id": station_id,
        "num_bikes_available": bikes,
        "num_docks_available": docks,
        "is_installed": installed,
        "is_renting": renting,
        "is_returning": returning,
    }


class StationMapTest(TestCase):
    def test_occupancy_percent_keeps_free_and_full_distinct(self):
        for bikes, docks, expected in (
            (0, 0, UNKNOWN_OCCUPANCY), (0, 20, 0), (1, 999, 1),
            (1, 3, 25), (1, 1, 50), (3, 1, 75), (999, 1, 99), (20, 0, 100),
        ):
            with self.subTest(bikes=bikes, docks=docks):
                self.assertEqual(occupancy_percent(bikes, docks), expected)

    def test_palette_interpolates_between_legend_stops(self):
        colors = occupancy_palette()
        self.assertEqual(len(colors), 101)
        self.assertEqual([percent for percent, _ in OCCUPANCY_GRADIENT], [0, 25, 50, 75, 100])
        for percent, expected in OCCUPANCY_GRADIENT:
            self.assertEqual(colors[percent], expected)
        self.assertNotIn(colors[55], (colors[50], colors[60]))

    def test_counts_critical_operational_snapshots_across_days(self):
        with TemporaryDirectory() as directory:
            for day, rows in enumerate((
                [status(10, 2, 2), status(10, 1, 2), status(10, 2, 1), status(10, 1, 1)],
                [
                    status(10, 2, 1),
                    status(10, None, 0),
                    status(10, -1, 0),
                    status(20, 3, 0, renting=0),
                    status(30, 0, 0, installed=0),
                    status(30, 0, 0, renting=0, returning=0),
                ],
            ), start=1):
                partition = Path(directory) / f"date=2026-10-{day:02}"
                partition.mkdir()
                pq.write_table(pa.Table.from_pylist(rows), partition / "station_status_test.parquet")

            counts, dates, files = summarize_status(Path(directory))

        self.assertEqual(counts, {10: (5, 4), 20: (1, 1)})
        self.assertEqual(dates, "2026-10-01 to 2026-10-02")
        self.assertEqual(files, 2)

    def test_occupancy_and_colors_use_first_snapshot_of_each_quarter_hour(self):
        with TemporaryDirectory() as directory:
            partition = Path(directory) / "date=2026-10-25"
            partition.mkdir()
            for stamp, rows in {
                "20261025T022200+0200": [status(10, 8, 2), status(20, 9, 1)],
                "20261025T021700+0200": [status(10, 2, 8)],
                "20261025T020200+0200": [status(10, 9, 1), status(20, 5, 5)],
                "20261025T010300Z": [status(10, 1, 9), status(20, 8, 0), status(30, 5, 5, installed=0)],
            }.items():
                pq.write_table(pa.Table.from_pylist(rows), partition / f"station_status_{stamp}.parquet")

            intervals = quarter_hour_occupancy(Path(directory), [20, 10, 30])["2026-10-25"]

        self.assertEqual(len(intervals), 100)
        self.assertEqual(intervals[10], {"label": "02:30 CEST", "occupancy": None})
        self.assertEqual(intervals[8]["captured"], "02:02:00 CEST")
        self.assertEqual(intervals[9]["captured"], "02:17:00 CEST")
        self.assertEqual(intervals[12]["captured"], "02:03:00 CET")
        for index, network_occupancy, station_occupancy in (
            (8, 70.0, [50, 90, UNKNOWN_OCCUPANCY]),
            (9, 20.0, [UNKNOWN_OCCUPANCY, 20, UNKNOWN_OCCUPANCY]),
            (12, 50.0, [100, 10, UNKNOWN_OCCUPANCY]),
        ):
            self.assertEqual(intervals[index]["occupancy"], network_occupancy)
            self.assertEqual(b64decode(intervals[index]["states"]), bytes(station_occupancy))

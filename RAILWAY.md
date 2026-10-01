# Railway Deployment

Decision: run the Velib collector as one persistent Railway service with one
Railway Volume.

Why this path:
- the collector must keep running when the local PC is off;
- the raw data is naturally file-based Parquet snapshots;
- a database is unnecessary until we need live querying or a dashboard.

## Railway Setup

1. Push this repo to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Let Railway build from the `Dockerfile`.
4. Add a Volume to the collector service.
5. Mount the Volume at `/data`.
6. Deploy the service.

When a Railway Volume is attached, Railway provides `RAILWAY_VOLUME_MOUNT_PATH`.
The collector detects it automatically and writes to:

```text
$RAILWAY_VOLUME_MOUNT_PATH/station_status/
```

With the recommended `/data` mount, files are written to:

```text
/data/station_status/date=YYYY-MM-DD/station_status_YYYYMMDDTHHMMSSZ.parquet
```

## Optional Variables

Set these only if you want to override defaults:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `VELIB_OUTPUT_DIR` | Railway volume path or `data/raw/station_status` | Explicit output directory |
| `VELIB_POLL_INTERVAL_SECONDS` | `300` | Polling interval |

## Local Test

```powershell
python -m pip install -r requirements.txt
python src\collect_velib.py --self-test
python src\collect_velib.py --once
```

## Downloading Data Later

Use Railway's Volume file browser or CLI to download the Parquet files from the
mounted volume.


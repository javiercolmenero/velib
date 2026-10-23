import base64
import io
import os
import re
import shutil
import subprocess
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

START_DATE = date(2026, 10, 1)    # <<< FIRST Paris day to keep (inclusive)
END_DATE = date(2026, 10, 14)     # <<< LAST Paris day to keep (inclusive) = first two weeks

OUT_DIR = Path("station_status")  # the ONLY folder this creates: station_status/date=<PARIS date>/...

PROJECT = "5393dde5-0995-4cdd-87dd-affd4544ee68"
ENVIRONMENT = "cdaea9f4-b468-428d-b7b3-c07b4e434d7f"
SERVICE = "9ae1a54c-d16c-4d45-a620-e4e62210ece2"

# Clean slate: remove the output folder and the old folders from earlier versions.
for old in (OUT_DIR, Path("_raw_utc"), Path("station_status_paris")):
    shutil.rmtree(old, ignore_errors=True)


def fetch_utc_day(day: date) -> bytes | None:
    """Download one UTC day folder as tar.gz bytes (None if that day has no data)."""
    remote = (
        f"echo ==BEGIN==; cd /data && tar czf - station_status/date={day.isoformat()} "
        f"2>/dev/null | base64 -w0; echo; echo ==END=="
    )
    cmd = [
        "railway.cmd", "ssh",
        "--project", PROJECT, "--environment", ENVIRONMENT, "--service", SERVICE,
        "--", remote,
    ]
    for attempt in range(3):
        out = subprocess.run(cmd, capture_output=True   , text=True)
        text = out.stdout
        if "==BEGIN==" in text and "==END==" in text:
            b64 = "".join(text.split("==BEGIN==")[1].split("==END==")[0].split())
            return base64.b64decode(b64) if b64 else None
        print(f"  attempt {attempt + 1} failed, retrying... {out.stderr[:200]}")
    raise SystemExit(f"Could not download {day}. Last output:\n{text[:500]}")


# A Paris day spans two UTC folders, so fetch one UTC day before and after the range.
first_utc = START_DATE - timedelta(days=1)
last_utc = END_DATE + timedelta(days=1)

pattern = re.compile(r"station_status_(\d{8}T\d{6})Z\.parquet")
per_day: dict[date, int] = {}

utc_day = first_utc
while utc_day <= last_utc:
    print(f"UTC day {utc_day} ...", end=" ", flush=True)
    data = fetch_utc_day(utc_day)
    if data is None:
        print("no data")
        utc_day += timedelta(days=1)
        continue

    saved = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            m = pattern.fullmatch(Path(member.name).name)
            if not m:
                continue
            utc = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            paris = utc.astimezone(PARIS)
            if not (START_DATE <= paris.date() <= END_DATE):
                continue
            dest_dir = OUT_DIR / f"date={paris.date().isoformat()}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Filename is now PARIS local time, with the offset (+0200 / +0100) to stay unambiguous.
            name = f"station_status_{paris.strftime('%Y%m%dT%H%M%S%z')}.parquet"
            dest_file = dest_dir / name
            dest_file.write_bytes(tar.extractfile(member).read())
            os.utime(dest_file, (member.mtime, member.mtime))   # restore the original extraction time
            per_day[paris.date()] = per_day.get(paris.date(), 0) + 1
            saved += 1
    print(f"{saved} files kept")
    utc_day += timedelta(days=1)

for d in sorted(per_day):
    print(f"  {d}: {per_day[d]}")
print(f"\nDone: {sum(per_day.values())} files in {OUT_DIR}/")
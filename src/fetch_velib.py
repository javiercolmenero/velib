import base64
import io
import subprocess
import tarfile
from datetime import date, timedelta

START_DATE = date(2026, 10, 1)    # <<< FIRST day to download (inclusive)
END_DATE = date(2026, 10, 14)     # <<< LAST day to download (inclusive) = first two weeks

days = [START_DATE + timedelta(d) for d in range((END_DATE - START_DATE).days + 1)]
paths = " ".join(f"station_status/date={d.isoformat()}" for d in days)
remote = (
    f"echo ==BEGIN==; cd /data && tar czf - {paths} | base64 -w0; echo; echo ==END=="
)

print("Downloading, this can take a few minutes...")    
out = subprocess.run(
    [
        "railway.cmd", "ssh",
        "--project", "5393dde5-0995-4cdd-87dd-affd4544ee68",
        "--environment", "cdaea9f4-b468-428d-b7b3-c07b4e434d7f",
        "--service", "9ae1a54c-d16c-4d45-a620-e4e62210ece2",
        "--", remote,
    ],
    capture_output=True, text=True,
)
text = out.stdout
if "==BEGIN==" not in text or "==END==" not in text:
    raise SystemExit(f"Unexpected output:\n{text[:500]}\n{out.stderr[:500]}")

b64 = "".join(text.split("==BEGIN==")[1].split("==END==")[0].split())
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz") as tar:
    tar.extractall(".")
print("Done: see the station_status folder")
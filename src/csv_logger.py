"""Write the per-sensor util dicts from pid.py to CSV files in <project>/logs/<session stamp>/."""
import csv
from datetime import datetime
from pathlib import Path

LOG_ROOT = Path(__file__).resolve().parent.parent / "logs"
FIELDS = ["timestamp", "pids", "ram", "cpu", "gpu_vram", "gpu_sm"]


def log_sensors(session_stamp, **sensors):
    """log_sensors(stamp, lidar=lidar_util, camera=camera_util, ...) -> logs/<stamp>/<sensor>.csv
    Pass the same stamp for the whole session so every call appends to the same folder."""
    log_dir = LOG_ROOT / session_stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="milliseconds")

    for sensor, util in sensors.items():
        path = log_dir / f"{sensor}.csv"
        new_file = not path.exists()
        gpu = util.get("gpu") or {}

        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({
                "timestamp": timestamp,
                "pids": " ".join(map(str, util["pids"])),
                "ram": util["ram"],
                "cpu": util["cpu"],
                "gpu_vram": gpu.get("vram", 0),
                "gpu_sm": gpu.get("sm", 0),
            })

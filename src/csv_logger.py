"""Write the per-sensor util dicts from pid.py, plus ROS sensor info, to CSV files in <project>/logs/<session stamp>/."""
import csv
from datetime import datetime
from pathlib import Path

LOG_ROOT = Path(__file__).resolve().parent.parent / "logs"

BASE_FIELDS = ["timestamp", "pids", "ram", "cpu", "cpu_overall", "gpu_vram", "gpu_sm"]

ROS_FIELDS = {
    "lidar": ["sensor_stamp_ns", "width", "height", "npts", "pt_step",
              "cloud_size_bytes", "is_dense", "hz", "hz_stamp"],
    "camera": ["sensor_stamp_ns", "width", "height", "npixels", "encoding", "step",
               "is_bigendian", "img_size_bytes", "hz", "hz_stamp"],
}

DCCS_FIELDS = ["timestamp", "dccs", "ram_util_mb", "ram_avail_mb", "ram_swap_mb",
               "cpu_freq_mhz", "cpu_utilization_pct", "cpu_temp_c", "cpu_power_w", "params_used"]

PARAMS_USED = ("cpu_freq_mhz_norm, cpu_utilization_pct_norm, gpu_mem_clock_mhz_norm, "
               "gpu_mem_pct_norm, gpu_pct_norm, gpu_sm_clock_mhz_norm, gpu_vram_mib_norm")


def _append_row(path, fields, row):
    """Append one row; write the header only if the file is new."""
    new_file = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def _ros_row(ros):
    """Map the monitor's dict to CSV columns (now_stamp_ns -> sensor_stamp_ns)."""
    if not ros:
        return {}
    row = dict(ros)
    row["sensor_stamp_ns"] = row.pop("now_stamp_ns", None)
    return row


def log_sensors(session_stamp, dccs=None, metrics=None, ros_lidar=None, ros_camera=None, **sensors):
    """log_sensors(stamp, dccs, metrics, ros_lidar=snap["lidar"], ros_camera=snap["cam"],
                   lidar=lidar_util, camera=camera_util, ...) -> logs/<stamp>/<sensor>.csv
    Pass the same stamp for the whole session so every call appends to the same folder."""
    log_dir = LOG_ROOT / session_stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="milliseconds")

    ros_by_sensor = {"lidar": ros_lidar, "camera": ros_camera}

    for sensor, util in sensors.items():
        gpu = util.get("gpu") or {}
        row = {
            "timestamp": timestamp,
            "pids": " ".join(map(str, util["pids"])),
            "ram": util["ram"],
            "cpu": util["cpu"],
            "cpu_overall": util["cpu_overall"],
            "gpu_vram": gpu.get("vram", 0),
            "gpu_sm": gpu.get("sm", 0),
        }
        row.update(_ros_row(ros_by_sensor.get(sensor)))

        fields = BASE_FIELDS + ROS_FIELDS.get(sensor, [])
        _append_row(log_dir / f"{sensor}.csv", fields, row)

    # DCCS: once per call, not once per sensor
    if dccs is not None and metrics is not None:
        _append_row(log_dir / "dccs.csv", DCCS_FIELDS, {
            "timestamp": timestamp,
            "dccs": round(dccs, 4),
            "ram_util_mb": metrics["ram"]["ram_util_mb"],
            "ram_avail_mb": metrics["ram"]["ram_avail_mb"],
            "ram_swap_mb": metrics["ram"]["ram_swap_mb"],
            "cpu_freq_mhz": metrics["cpu"]["cpu_freq_mhz"],
            "cpu_utilization_pct": metrics["cpu"]["cpu_utilization_pct"],
            "cpu_temp_c": metrics["cpu"]["cpu_temp_c"],
            "cpu_power_w": metrics["cpu"]["cpu_power_w"],
            "params_used": PARAMS_USED,
        })
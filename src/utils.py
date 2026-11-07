"""Helpers for static_specs.py. No collectors in here, only parsing / lookup / command utilities."""
import json
import re
import subprocess

def bytes2MB (bytes):
    return round(int(bytes) / (1024 * 1024), 2)

# ---------------------------------------------------------------- commands / files
def run_cmd(cmd, as_json=False, strict=True):
    """Run a command, return stdout (or parsed JSON). None on any failure.
    strict=False accepts non-zero exit codes (smartctl uses them as status flags)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if (strict and r.returncode != 0) or not r.stdout.strip():
        return None
    if as_json:
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
    return r.stdout


def read_sysfs(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


# ---------------------------------------------------------------- parsing
def parse_number(s):
    """'2933 MT/s' -> 2933.0, None if no leading number."""
    m = re.match(r"\s*([\d.]+)", str(s) if s is not None else "")
    return float(m.group(1)) if m else None


def parse_int(s):
    n = parse_number(s)
    return int(n) if n is not None else None


def parse_size_gib(s):
    """'8192 MB' / '16 GB' -> GiB as float, None if not a size (e.g. 'No Module Installed')."""
    m = re.match(r"\s*(\d+)\s*(KB|MB|GB|TB)", s or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n / {"KB": 2**20, "MB": 2**10, "GB": 1, "TB": 1 / 1024}[unit]


def parse_cache_per_instance_kib(s):
    """'192 KiB (6 instances)' -> 32.  Older lscpu: '32 KiB' / '32K' -> 32.  L3 in MiB is converted to KiB."""
    m = re.match(r"\s*([\d.]+)\s*([KMG])i?B?(?:\s*\((\d+) instance)?", s or "")
    if not m:
        return None
    size = float(m.group(1)) * {"K": 1, "M": 1024, "G": 1024**2}[m.group(2)]
    return int(size / int(m.group(3) or 1))


def parse_base_freq_mhz(model_name):
    """'Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz' -> 2600.0"""
    m = re.search(r"@\s*([\d.]+)\s*GHz", model_name or "")
    return float(m.group(1)) * 1000 if m else None


def to_bool(v):
    """lsblk gives ROTA as bool or '0'/'1' depending on version."""
    if isinstance(v, bool):
        return v
    if v in ("1", 1):
        return True
    if v in ("0", 0):
        return False
    return None


def flatten(entries, out=None):
    """Flatten the nested lscpu -J tree into {field_name: value}."""
    out = {} if out is None else out
    for e in entries:
        out[e["field"].strip().rstrip(":")] = e["data"]
        flatten(e.get("children", []), out)
    return out


# ---------------------------------------------------------------- RAM
def run_dmidecode_memory():
    """Return dmidecode text, or None if it can't run (not root, not installed)."""
    try:
        r = subprocess.run(["dmidecode", "-t", "memory"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return r.stdout if r.returncode == 0 else None


def parse_memory_devices(text):
    """One dict per 'Memory Device' block (including empty slots)."""
    devices = []
    if not text:
        return devices
    for block in text.split("\n\n"):
        lines = block.strip().splitlines()
        if not any(l.strip() == "Memory Device" for l in lines[:3]):
            continue
        d = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)      # split on FIRST colon only
                d[k.strip()] = v.strip()
        devices.append(d)
    return devices


def infer_channels(populated):
    """Count distinct 'Channel X' ids in the locator strings.
    Returns (channels, method). Method says how much to trust it."""
    ids = set()
    for d in populated:
        text = f"{d.get('Bank Locator', '')} {d.get('Locator', '')}"
        m = re.search(r"channel[\s_-]*([A-Za-z0-9]+)", text, re.IGNORECASE)
        if m:
            ids.add(m.group(1).upper())
    if ids:
        return len(ids), "locator"
    if populated:
        return len(populated), "assumed_one_per_dimm"
    return None, None


# ---------------------------------------------------------------- GPU
CORES_PER_SM = {
    (5, 0): 128, (5, 2): 128, (6, 0): 64, (6, 1): 128,
    (7, 0): 64, (7, 2): 64, (7, 5): 64,
    (8, 0): 64, (8, 6): 128, (8, 7): 128, (8, 9): 128,
    (9, 0): 128, (10, 0): 128, (12, 0): 128,
}


def safe_call(fn, *args):
    """Call an NVML function; None if unsupported (common on laptops)."""
    try:
        v = fn(*args)
    except Exception as e:
        print("safe_call Exception: ", e)
        return None
    return v.decode() if isinstance(v, bytes) else v


def sm_count_via_torch(index):
    try:
        import torch
        return torch.cuda.get_device_properties(index).multi_processor_count
    except Exception:
        return None


# ---------------------------------------------------------------- PCIe
GTS_TO_GEN = {2.5: 1, 5.0: 2, 8.0: 3, 16.0: 4, 32.0: 5, 64.0: 6}
GEN_TO_GTS = {v: k for k, v in GTS_TO_GEN.items()}


def pcie_ceiling_gbs(gen, lanes):
    """Theoretical one-direction throughput in GB/s after encoding overhead.
    Gen 6 uses different encoding, so treat it as approximate."""
    if not gen or not lanes or gen not in GEN_TO_GTS:
        return None
    eff = 0.8 if gen <= 2 else 128 / 130
    return round(GEN_TO_GTS[gen] * eff / 8 * lanes, 2)


# ---------------------------------------------------------------- fio
def run_fio(filename, rw, bs, iodepth, size="1G", runtime=10, ioengine="libaio"):
    cmd = ["fio", "--name=cc", f"--filename={filename}", f"--size={size}",
           f"--rw={rw}", f"--bs={bs}", "--direct=1", f"--ioengine={ioengine}",
           f"--iodepth={iodepth}", f"--runtime={runtime}", "--time_based",
           "--output-format=json"]
    data = run_cmd(cmd, as_json=True)
    if not data:
        return None
    job = data["jobs"][0]
    side = job["read"] if "read" in rw else job["write"]
    bw = side.get("bw_bytes") or side["bw"] * 1024
    return {"bw_mbs": round(bw / 1e6, 1),
            "iops": round(side["iops"]),
            "lat_mean_us": round(side["clat_ns"]["mean"] / 1e3, 1)}

def collect_live_gpu():
    try:
        import pynvml as nv
        nv.nvmlInit()
    except Exception as e:
        print(f"GPU collector: NVML unavailable ({e})")
        return None

    try:
        handle = nv.nvmlDeviceGetHandleByIndex(0)
        gpu_mem_util_pct = safe_call(nv.nvmlDeviceGetUtilizationRates, handle)
        sm_clock_mhz = safe_call(nv.nvmlDeviceGetClockInfo, handle, nv.NVML_CLOCK_SM)
        mem_clock_mhz = safe_call(nv.nvmlDeviceGetClockInfo, handle, nv.NVML_CLOCK_MEM)
        vram_mib = safe_call(nv.nvmlDeviceGetMemoryInfo, handle).used / (1024 * 1024)
        temp_c = safe_call(nv.nvmlDeviceGetTemperature, handle, nv.NVML_TEMPERATURE_GPU)
        gpu_power_w = safe_call(nv.nvmlDeviceGetPowerUsage, handle) / 1000

    finally:
        try:
            nv.nvmlShutdown()
        except Exception:
            pass   

    return {
        "gpu_pct": gpu_mem_util_pct.gpu,
        "gpu_mem_pct": gpu_mem_util_pct.memory,
        "gpu_sm_clock_mhz": sm_clock_mhz,
        "gpu_mem_clock_mhz": mem_clock_mhz,
        "gpu_vram_mib": vram_mib,
        "gpu_temp_c": temp_c,
        "gpu_power_w": gpu_power_w
    }
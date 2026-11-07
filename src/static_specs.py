"""Static spec collector for the computational-cost framework.

Usage:
    sudo python3 static_specs.py                 # RAM and SATA details need root
    sudo python3 static_specs.py --path /data    # drive that holds your logs/datasets
    sudo python3 static_specs.py --bench         # also run the fio storage benchmark (slow)

Every collector returns a plain dict. Anything it cannot read is None, never a crash.
"""
import argparse
import json
import os
import platform
import re

import psutil

from utils import (
    CORES_PER_SM, GTS_TO_GEN, flatten, infer_channels, parse_base_freq_mhz,
    parse_cache_per_instance_kib, parse_int, parse_memory_devices, parse_number,
    parse_size_gib, pcie_ceiling_gbs, read_sysfs, run_cmd, run_dmidecode_memory,
    run_fio, safe_call, sm_count_via_torch, to_bool,
)


# ====================================================================== CPU
def collect_cpu():
    raw = run_cmd(["lscpu", "-J"], as_json=True)
    if not raw:
        print("CPU collector: lscpu failed")
        return None
    f = flatten(raw["lscpu"])

    sockets = parse_int(f.get("Socket(s)")) or 1
    cores_per_socket = parse_int(f.get("Core(s) per socket"))
    tpc = parse_int(f.get("Thread(s) per core"))

    physical = sockets * cores_per_socket if cores_per_socket else None
    threads = physical * tpc if (physical and tpc) else None

    # base frequency: sysfs (kHz) if present, otherwise parse the model name string
    base_khz = parse_number(read_sysfs("/sys/devices/system/cpu/cpu0/cpufreq/base_frequency"))
    base_mhz = base_khz / 1000 if base_khz else parse_base_freq_mhz(f.get("Model name"))

    return {
        # "model": f.get("Model name"),
        "architecture": f.get("Architecture"),
        # "family_model_stepping": [f.get("CPU family"), f.get("Model"), f.get("Stepping")],
        "sockets": sockets,
        "physical_cores": physical,
        "threads_per_core": tpc,
        "threads_total": threads,
        "base_freq_mhz": base_mhz,
        "min_freq_mhz": parse_number(f.get("CPU min MHz")),
        "max_freq_mhz": parse_number(f.get("CPU max MHz")),
        "l1d_kib_per_core": parse_cache_per_instance_kib(f.get("L1d cache")),
        "l1i_kib_per_core": parse_cache_per_instance_kib(f.get("L1i cache")),
        "l2_kib_per_core": parse_cache_per_instance_kib(f.get("L2 cache")),
        "l3_kib_shared": parse_cache_per_instance_kib(f.get("L3 cache")),
        # informational flags only (not part of the formal CC definition)
        # "isa_flags": {
        #     flag: (flag in (f.get("Flags") or "").split())
        #     for flag in ("sse4_2", "avx", "avx2", "fma", "avx512f", "aes")
        # },
    }


# ====================================================================== RAM
def collect_ram():
    if os.geteuid() != 0:
        print("WARNING: not root, dmidecode fields will be None (run with sudo)")

    devices = parse_memory_devices(run_dmidecode_memory())
    populated = [d for d in devices if parse_size_gib(d.get("Size")) is not None]
    swap_gib = round(psutil.swap_memory().total / 2**30, 2)

    # fallback when dmidecode is unavailable: usable RAM from the kernel
    if not populated:
        return {
            "capacity_gib": round(psutil.virtual_memory().total / 2**30, 1),
            # "capacity_source": "psutil (usable, slightly below installed)",
            "type": None, "rated_speed_mts": None, "configured_speed_mts": None,
            "slots_total": None, "slots_populated": None,
            "channels": None, "channels_method": None,
            "bandwidth_gbs": None, "ecc": None, "swap_gib": swap_gib,
        }

    capacity = sum(parse_size_gib(d["Size"]) for d in populated)
    first = populated[0]

    rated = parse_int(first.get("Speed"))
    configured = parse_int(
        first.get("Configured Memory Speed") or first.get("Configured Clock Speed")
    )
    speed_for_bw = configured or rated

    channels, method = infer_channels(populated)

    bandwidth = None
    if speed_for_bw and channels:
        # assumes 64-bit channels (DDR4/DDR5 DIMMs). Soldered LPDDR differs.
        bandwidth = round(speed_for_bw * 8 * channels / 1000, 1)   # GB/s

    # ECC: total width wider than data width (e.g. 72 vs 64)
    tw, dw = parse_int(first.get("Total Width")), parse_int(first.get("Data Width"))
    ecc = (tw > dw) if (tw and dw) else None

    return {
        "capacity_gib": round(capacity, 1),
        # "capacity_source": "dmidecode (installed)",
        "type": first.get("Type"),
        "rated_speed_mts": rated,
        "configured_speed_mts": configured,
        "slots_total": len(devices),
        "slots_populated": len(populated),
        "channels": channels,
        "channels_method": method,        # "locator" is reliable, the other is a guess
        "bandwidth_gbs": bandwidth,
        "ecc": ecc,
        "swap_gib": swap_gib,
    }


# ====================================================================== GPU
def collect_gpu():
    try:
        import pynvml as nv
        nv.nvmlInit()
    except Exception as e:
        print(f"GPU collector: NVML unavailable ({e})")
        return None

    try:
        driver = safe_call(nv.nvmlSystemGetDriverVersion)
        cuda_int = safe_call(nv.nvmlSystemGetCudaDriverVersion)   # e.g. 12040
        cuda_ver = f"{cuda_int // 1000}.{(cuda_int % 1000) // 10}" if cuda_int else None

        gpus = []
        for i in range(nv.nvmlDeviceGetCount()):
            h = nv.nvmlDeviceGetHandleByIndex(i)

            cc = safe_call(nv.nvmlDeviceGetCudaComputeCapability, h)     # (major, minor)
            cores = safe_call(nv.nvmlDeviceGetNumGpuCores, h)            # newer drivers only
            per_sm = CORES_PER_SM.get(tuple(cc)) if cc else None

            sm = cores // per_sm if (cores and per_sm) else sm_count_via_torch(i)
            if cores is None and sm and per_sm:
                cores = sm * per_sm

            mem = safe_call(nv.nvmlDeviceGetMemoryInfo, h)
            max_sm = safe_call(nv.nvmlDeviceGetMaxClockInfo, h, nv.NVML_CLOCK_SM)
            max_mem = safe_call(nv.nvmlDeviceGetMaxClockInfo, h, nv.NVML_CLOCK_MEM)
            bus = safe_call(nv.nvmlDeviceGetMemoryBusWidth, h)

            # estimate only: assumes a double-data-rate memory clock (GDDR6 style)
            bw = round(bus / 8 * max_mem * 2 / 1000, 1) if (bus and max_mem) else None

            default_w = safe_call(nv.nvmlDeviceGetPowerManagementDefaultLimit, h)
            limits = safe_call(nv.nvmlDeviceGetPowerManagementLimitConstraints, h)  # (min, max) mW

            pcie_gen = safe_call(nv.nvmlDeviceGetMaxPcieLinkGeneration, h)
            pcie_w = safe_call(nv.nvmlDeviceGetMaxPcieLinkWidth, h)

            gpus.append({
                "index": i,
                "model": safe_call(nv.nvmlDeviceGetName, h),
                "compute_capability": f"{cc[0]}.{cc[1]}" if cc else None,
                "sm_count": sm,
                "cuda_cores": cores,
                "max_sm_clock_mhz": max_sm,
                "max_mem_clock_mhz": max_mem,
                "vram_gib": round(mem.total / 2**30, 2) if mem else None,
                "bus_width_bits": bus,
                "bandwidth_gbs_est": bw,
                "power_default_w": default_w / 1000 if default_w else None,
                "power_max_w": limits[1] / 1000 if limits else None,
                "pcie_max_gen": pcie_gen,
                "pcie_max_width": pcie_w,
                "pcie_ceiling_gbs": pcie_ceiling_gbs(pcie_gen, pcie_w),
                "driver_version": driver,
                "cuda_driver_version": cuda_ver,
                "vbios": safe_call(nv.nvmlDeviceGetVbiosVersion, h),
            })
        return gpus
    finally:
        try:
            nv.nvmlShutdown()
        except Exception:
            pass




# ====================================================================== Storage
def find_backing_disk(path):
    """Resolve path -> mount info + the physical disk underneath (through LVM/LUKS)."""
    out = run_cmd(["findmnt", "-no", "SOURCE,FSTYPE,OPTIONS", "-T", path])
    if not out:
        return None
    src, fstype, opts = out.strip().split(None, 2)
    src = re.sub(r"\[.*\]$", "", src)            # btrfs shows /dev/x[/@subvol]

    info = {"source": src, "fstype": fstype, "mount_options": opts,
            "disk": None, "encrypted": None}

    tree = run_cmd(["lsblk", "-J", "-b", "-s", "-o",
                    "NAME,TYPE,MODEL,SIZE,ROTA,TRAN,SERIAL", src], as_json=True)
    if not tree:                                 # tmpfs, overlay, network mounts
        return info

    chain, node = [], tree["blockdevices"][0]
    while node:                                  # -s lists parents as "children"
        chain.append(node)
        kids = node.get("children")
        node = kids[0] if kids else None        # follows the first parent only

    info["disk"] = next((n for n in chain if n["type"] == "disk"), None)
    info["encrypted"] = any(n["type"] == "crypt" for n in chain)
    return info


def read_nvme_link(disk_name):
    m = re.match(r"(nvme\d+)n\d+", disk_name)
    if not m:
        return {}
    ctrl = f"/sys/class/nvme/{m.group(1)}"
    pci = f"{ctrl}/device"
    cur = parse_number(read_sysfs(f"{pci}/current_link_speed"))     # GT/s
    mx = parse_number(read_sysfs(f"{pci}/max_link_speed"))
    cur_w = parse_int(read_sysfs(f"{pci}/current_link_width"))
    max_w = parse_int(read_sysfs(f"{pci}/max_link_width"))
    gen_max, gen_cur = GTS_TO_GEN.get(mx), GTS_TO_GEN.get(cur)
    return {
        "model": read_sysfs(f"{ctrl}/model"),
        "firmware": read_sysfs(f"{ctrl}/firmware_rev"),
        "pcie_max_gen": gen_max,
        "pcie_max_width": max_w,
        "pcie_current_gen": gen_cur,
        "pcie_current_width": cur_w,
        "link_ceiling_gbs": pcie_ceiling_gbs(gen_max, max_w),
    }


def collect_storage(path="."):
    path = os.path.abspath(path)
    usage = psutil.disk_usage(path)
    info = find_backing_disk(path)
    if info is None:
        return None

    specs = {
        "path": path,
        "device": info["source"],
        "filesystem": info["fstype"],
        "mount_options": info["mount_options"],
        "encrypted_luks": info["encrypted"],
        "fs_total_gib": round(usage.total / 2**30, 1),
        "fs_free_gib_at_collection": round(usage.free / 2**30, 1),   # informational, not static
        "type": None, "model": None, "firmware": None,
        "disk_capacity_gib": None, "interface": None, "link": {},
    }

    disk = info["disk"]
    if disk is None:                              # not a block device (tmpfs, NFS...)
        return specs

    name, tran, rota = disk["name"], disk.get("tran"), to_bool(disk.get("rota"))
    if tran == "nvme":
        kind = "NVMe SSD"
    elif rota:
        kind = "HDD"
    elif rota is False:
        kind = "SATA SSD" if tran == "sata" else "SSD"
    else:
        kind = None

    specs["type"] = kind
    specs["interface"] = tran
    specs["disk_capacity_gib"] = round(int(disk["size"]) / 2**30, 1)
    specs["model"] = (disk.get("model") or "").strip() or read_sysfs(f"/sys/block/{name}/device/model")
    specs["firmware"] = (read_sysfs(f"/sys/block/{name}/device/rev")
                         or read_sysfs(f"/sys/block/{name}/device/firmware_rev"))

    if tran == "nvme":
        link = read_nvme_link(name)
        specs["model"] = link.pop("model", None) or specs["model"]
        specs["firmware"] = link.pop("firmware", None) or specs["firmware"]
        specs["link"] = link
    elif tran == "sata":                          # smartctl needs root
        sm = run_cmd(["smartctl", "-i", "-j", f"/dev/{name}"], as_json=True, strict=False)
        if sm:
            speed = sm.get("interface_speed", {})
            specs["link"] = {
                "sata_max": speed.get("max", {}).get("string"),
                "sata_current": speed.get("current", {}).get("string"),
            }
            specs["firmware"] = specs["firmware"] or sm.get("firmware_version")
    return specs


def benchmark_storage(path=".", size="1G", runtime=10):
    """Measured numbers (static for fixed hardware). Run once, on the real data drive."""
    path = os.path.abspath(path)
    test_file = os.path.join(path, "cc_fio_test.bin")
    if psutil.disk_usage(path).free < 2 * 2**30:
        print("Not enough free space for the fio test")
        return None
    try:
        sw = run_fio(test_file, "write", "1M", 16, size, runtime)       # write first: creates the file
        sr = run_fio(test_file, "read", "1M", 16, size, runtime)
        rw = run_fio(test_file, "randwrite", "4k", 32, size, runtime)
        rr = run_fio(test_file, "randread", "4k", 32, size, runtime)
        lat = run_fio(test_file, "randread", "4k", 1, size, runtime)    # QD1 = true latency
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

    g = lambda d, k: d[k] if d else None
    return {
        "seq_read_mbs": g(sr, "bw_mbs"),
        "seq_write_mbs": g(sw, "bw_mbs"),
        "rand_read_iops_4k": g(rr, "iops"),
        "rand_write_iops_4k": g(rw, "iops"),
        "rand_read_latency_us_qd1": g(lat, "lat_mean_us"),
    }


# ====================================================================== Software stack
def collect_software():
    """Not hardware, but a change here also invalidates results (see the draft's rule of thumb)."""
    return {
        "os": platform.platform(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu_governor": read_sysfs("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "intel_pstate_status": read_sysfs("/sys/devices/system/cpu/intel_pstate/status"),
        "cpu_turbo_disabled": read_sysfs("/sys/devices/system/cpu/intel_pstate/no_turbo"),
        "nvcc": (run_cmd(["nvcc", "--version"]) or "").strip().splitlines()[-1:] or None,
    }


# ====================================================================== entry point
def collect_all(data_path=".", bench=False):
    specs = {
        "cpu": collect_cpu(),
        "ram": collect_ram(),
        "gpu": collect_gpu(),
        "storage": collect_storage(data_path),
        "software": collect_software(),
    }
    if bench:
        specs["storage_bench"] = benchmark_storage(data_path)
    return specs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".", help="directory on the drive your experiments use")
    ap.add_argument("--bench", action="store_true", help="run the fio storage benchmark")
    ap.add_argument("--out", default="static.json")
    args = ap.parse_args()

    result = collect_all(args.path, args.bench)
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nSaved to {args.out}")
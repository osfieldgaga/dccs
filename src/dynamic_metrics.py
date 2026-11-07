import psutil
import time
import pprint
import json
from pathlib import Path

from utils import read_sysfs, collect_live_gpu

def compute_dccs():


    specs = json.loads(Path("./static.json").read_text())

    metrics = {}

    power_cnt_ms = 0
    power_last_time_ns = 0;
    prev_w_uj = 0;
    PWR_REFRESH_RATE_MS = 1000
    
    # ---- CPU

    cpu_power_w = 0

    power_counter_elapsed_ms= (time.time_ns() - power_last_time_ns) / 1000000
    if power_counter_elapsed_ms >= PWR_REFRESH_RATE_MS:
        
        
        # this can roll over, need to be added to max_energy_range_uj to prevent negative spikes when it happens
        uj = int(read_sysfs("/sys/class/powercap/intel-rapl:0/energy_uj"))


        if prev_w_uj == 0:
            #nada
            ...
        else:    
            if (uj - prev_w_uj < 0): # rollover
                uj = uj + int(read_sysfs("/sys/class/powercap/intel-rapl:0/max_energy_range_uj"))
            
            uW = (uj - prev_w_uj)/(power_counter_elapsed_ms/1000)

            cpu_power_w = round(uW / 1000000, 2)


        prev_w_uj = uj
        power_last_time_ns = time.time_ns()

    # print(psutil.sensors_temperatures().)

    metrics["cpu"] = {
                "cpu_freq_mhz": round(psutil.cpu_freq().current, 2),
                "cpu_utilization_pct": psutil.cpu_percent(interval=0.2),
                "cpu_temp_c": psutil.sensors_temperatures()['coretemp'][0].current,
                "cpu_power_w": cpu_power_w,
                "cpu_throttling": "TBD",

            }
    

    ## ---- GPU: handled in utils
    
    metrics["gpu"] = collect_live_gpu()

    ## --- RAM

    ram_vmem = psutil.virtual_memory()

    metrics["ram"] = {
        "ram_util_mb": ram_vmem.used / (1024 ** 2),
        "ram_avail_mb": ram_vmem.available / (1024 ** 2),
        "ram_swap_mb": psutil.swap_memory().used / (1024 ** 2),
    }

    ## --- Utilization score 

    cpu_freq_mhz_norm = metrics["cpu"]["cpu_freq_mhz"] / specs["cpu"]["base_freq_mhz"]
    cpu_utilization_pct_norm = metrics["cpu"]["cpu_utilization_pct"] / 100

    gpu_mem_clock_mhz_norm = metrics["gpu"]["gpu_mem_clock_mhz"] / specs["gpu"][0]["max_mem_clock_mhz"]
    gpu_mem_pct_norm = metrics["gpu"]["gpu_mem_pct"] / 100
    gpu_pct_norm = metrics["gpu"]["gpu_pct"] / 100
    gpu_sm_clock_mhz_norm = metrics["gpu"]["gpu_sm_clock_mhz"] / specs["gpu"][0]["max_sm_clock_mhz"]
    gpu_vram_mib_norm = metrics["gpu"]["gpu_vram_mib"] / (specs["gpu"][0]["vram_gib"] * 1024)

    util_score =  (cpu_freq_mhz_norm + cpu_utilization_pct_norm + gpu_mem_clock_mhz_norm + 
                    gpu_mem_pct_norm + gpu_pct_norm + gpu_sm_clock_mhz_norm + gpu_vram_mib_norm) / 7

    return metrics, util_score

if __name__ == "__main__":




    while True:
   
        #
        metrics, util_score = compute_dccs()
        print(f"DCCS: {round(util_score * 100, 2)}/100")

        # pprint.pprint(metrics)
        print("\n")
        time.sleep(1)
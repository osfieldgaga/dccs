import psutil
from utils import bytes2MB, safe_call
from csv_logger import log_sensors
from datetime import datetime
import pprint

# set once when the script starts, all logs of this session go to logs/<SESSION_STAMP>/
SESSION_STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
from csv_logger import log_sensors

try:
    import pynvml as nv
    nv.nvmlInit()
except Exception as e:
    print(f"GPU collector: NVML unavailable ({e})")


# Define the names of the processes associated with the sensors
# a specific process name may be tied to multiple PIDs
# We care about the overall utilization for all PIDs under one process name
# TODO: fill these with actual process names
lidar_processes = ['code', 'Xorg']
camera_processes = ['chrome']
gps_processes = ['zotero-bin']
radar_processes = ['MATLAB']

# TODO: in scripts that process images, colelct the PIDS for each one into a shared file or over ROS then append it
#


def get_pids_gpu(pids):
    last_seen = 0

    o = {'vram': 0, 'sm': 0}

    for i in range(nv.nvmlDeviceGetCount()):
        h = nv.nvmlDeviceGetHandleByIndex(i)

        # compute
        try:
            comp_proc = safe_call(nv.nvmlDeviceGetComputeRunningProcesses, h)
        except nv.NVMLError:
            print("Can't collect GPU compute processes")

        # graphics
        try:
            graphic_proc = safe_call(nv.nvmlDeviceGetGraphicsRunningProcesses, h)
        except nv.NVMLError:
            print("Can't collect GPU graphics processes")

        # utilization %
        try:
            all_processes_pct = safe_call(nv.nvmlDeviceGetProcessUtilization, h, 1793991966951081)
        except nv.NVMLError:
            print("Can't collect GPU compute processes")

        all_processes_vram = comp_proc + graphic_proc

        # print('comp_gpu_pct', comp_gpu_pct)

        if not all_processes_vram:
            print(f"GPU {i:<4} No active processes found.")
            continue

        
        
        for idx, proc in enumerate(all_processes_vram):
            print(proc)

            
            if proc.pid in pids:
                mem_mib = bytes2MB(proc.usedGpuMemory) if proc.usedGpuMemory else 0
                o['vram'] += mem_mib

        # gpu_ts = 0
        # for idx, proc in enumerate(all_processes_pct):

        #     # take the first timestamp, use that for all
        #     if idx == 0: 
        #         gpu_ts = proc.timeStamp

        #     print('proc', proc)
        #     print('pid', proc.pid)
        #     print('smUtil', proc.smUtil, '%')
        #     print('memUtil', proc.memUtil, '%')

        # last_seen = max(s.timeStamp for s in all_processes_pct)
        # print(last_seen)

        return o

def get_pids_by_process(process_name):
    pids = []

    try: 
        for process in psutil.process_iter(['pid', 'name']):
        
                if process_name == process.info['name']:
                    pids.append(process.info['pid'])
    except psutil.NoSuchProcess():
        print(f"Process {process_name} does not exist.")
    except psutil.AccessDenied():
        print(f"Cannot fetch processes, access denied")
         

    return pids


try: 

    # print("Name:", p.name())
    # print("Status:", p.status())
    # print("CPU %:", p.cpu_percent(interval=0.1))
    # print("Memory Info:", p.memory_info())
    # print("Command line:", p.cmdline())

    # print("Reverting VS Code PIDs")

    lidar_pids = []
    camera_pids = []
    gps_pids = []
    radar_pids = []

    for lidar_process in lidar_processes:
        lidar_pids += get_pids_by_process(lidar_process)

    for camera_process in camera_processes:
        camera_pids += get_pids_by_process(camera_process)

    for gps_process in gps_processes:
        gps_pids += get_pids_by_process(gps_process)

    for radar_process in radar_processes:
        radar_pids += get_pids_by_process(radar_processes)

    lidar_util = {'pids': lidar_pids, 'ram': 0, 'cpu': 0, 'gpu': 0}
    camera_util = {'pids': camera_pids, 'ram': 0, 'cpu': 0, 'gpu': 0}
    gps_util = {'pids': gps_pids, 'ram': 0, 'cpu': 0, 'gpu': 0}
    radar_util = {'pids': radar_pids, 'ram': 0, 'cpu': 0, 'gpu': 0}

    for pid in lidar_pids:
        p = psutil.Process(pid)
        
        p_rss = p.memory_info().rss
        p_cpu = p.cpu_percent(interval=0.0)
        lidar_util['ram'] += bytes2MB(p_rss)
        lidar_util['cpu'] += p_cpu

    lidar_util['gpu'] = get_pids_gpu(lidar_pids)

    for pid in camera_pids:
        p = psutil.Process(pid)
        
        p_rss = p.memory_info().rss
        p_cpu = p.cpu_percent(interval=0.0)
        camera_util['ram'] += bytes2MB(p_rss)
        camera_util['cpu'] += p_cpu

    camera_util['gpu'] = get_pids_gpu(camera_pids)

    for pid in gps_pids:
        p = psutil.Process(pid)
        
        p_rss = p.memory_info().rss
        p_cpu = p.cpu_percent(interval=0.0)
        gps_util['ram'] += bytes2MB(p_rss)
        gps_util['cpu'] += p_cpu

    gps_util['gpu'] = get_pids_gpu(gps_pids)

    for pid in radar_pids:
        p = psutil.Process(pid)
        
        p_rss = p.memory_info().rss
        p_cpu = p.cpu_percent(interval=0.0)
        radar_util['ram'] += bytes2MB(p_rss)
        radar_util['cpu'] += p_cpu

    radar_util['gpu'] = get_pids_gpu(radar_pids)

    print("LiDAR:")
    pprint.pprint(lidar_util)
    print("\nCam:")
    pprint.pprint(camera_util)
    print("\nGPS:")
    pprint.pprint(gps_util)
    print("\nRadar:")
    pprint.pprint(radar_util)

    log_sensors(SESSION_STAMP, lidar=lidar_util, camera=camera_util, gps=gps_util, radar=radar_util)



    # pmem = p.memory_info()
    # print(bytes2MB(pmem.rss))

except psutil.Error as e:
    print("Error", e)
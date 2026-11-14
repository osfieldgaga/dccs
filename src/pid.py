"""
Just copy and run this; for ROS purposes
bash -c "source /opt/ros/humble/setup.bash && /home/autodrive/Desktop/DCCS/venv/bin/python /home/autodrive/Desktop/DCCS/src/pid.py"
"""

import psutil
from utils import bytes2MB, safe_call
from csv_logger import log_sensors
from datetime import datetime
import pprint
import time
from dynamic_metrics import compute_dccs, specs
from ros_monitor import SensorMonitor
import rclpy
import threading

rclpy.init()

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

lidar_processes = ['cepton_publisher_node', 'cepton_subscriber_node']
camera_processes = ['camera_driver_node']
gps_processes = ['novatel_oem7_driver_exe']
radar_processes = ['']

CAPTURE_PERIOD_MS = 1000

CAPTURE_PERIOD_NS = CAPTURE_PERIOD_MS *1000000 # don't change

utilities_processes = ['']

# TODO: in scripts that process images, colelct the PIDS for each one into a shared file or over ROS then append it


# TODO: A ROS node to log the current perfs of each sensor (point cloud density, camera resolution etc)
# TODO: log the computational footprint of the utilities (MATLAB, this script)


sensor_monitor = SensorMonitor()

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
            # print(proc)

            
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

def get_pids_by_process(process_name, allow_partial_match=False):
    pids = []

    try: 
        for process in psutil.process_iter(['pid', 'name']):

                if (allow_partial_match and process_name in process.info['name']):
                    print(process.info)
        
                if process_name == process.info['name'] or (allow_partial_match and process_name in process.info['name']):
                    pids.append(process.info['pid'])
    except psutil.NoSuchProcess():
        print(f"Process {process_name} does not exist.")
    except psutil.AccessDenied():
        print(f"Cannot fetch processes, access denied")
         

    return pids

init_dt = time.monotonic_ns()
last_dt = 0
dt = 0


def main():
    spin_thread = threading.Thread(target=rclpy.spin, args=(sensor_monitor,), daemon=True)
    spin_thread.start()
    print("spin thread started")

    period_s = CAPTURE_PERIOD_MS / 1000
    next_t = time.monotonic()

    try:
        while True:
            next_t += period_s
            try:
                last_dt = time.monotonic_ns()
                
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
                    p_cpu = p.cpu_percent(interval=0.2)
                    lidar_util['ram'] += bytes2MB(p_rss)
                    lidar_util['cpu'] += p_cpu

                lidar_util['gpu'] = get_pids_gpu(lidar_pids)
                lidar_util["cpu_overall"] = round(lidar_util['cpu'] / specs['cpu']['threads_total'], 2)

                for pid in camera_pids:
                    p = psutil.Process(pid)
                    
                    p_rss = p.memory_info().rss
                    p_cpu = p.cpu_percent(interval=0.2)
                    camera_util['ram'] += bytes2MB(p_rss)
                    camera_util['cpu'] += p_cpu

                camera_util['gpu'] = get_pids_gpu(camera_pids)
                camera_util["cpu_overall"] = round(camera_util['cpu'] / specs['cpu']['threads_total'], 2)

                for pid in gps_pids:
                    p = psutil.Process(pid)
                    
                    p_rss = p.memory_info().rss
                    p_cpu = p.cpu_percent(interval=0.2)
                    gps_util['ram'] += bytes2MB(p_rss)
                    gps_util['cpu'] += p_cpu

                gps_util['gpu'] = get_pids_gpu(gps_pids)
                gps_util["cpu_overall"] = round(gps_util['cpu'] / specs['cpu']['threads_total'], 2)

                for pid in radar_pids:
                    p = psutil.Process(pid)
                    
                    p_rss = p.memory_info().rss
                    p_cpu = p.cpu_percent(interval=0.2)
                    radar_util['ram'] += bytes2MB(p_rss)
                    radar_util['cpu'] += p_cpu

                radar_util['gpu'] = get_pids_gpu(radar_pids)
                radar_util["cpu_overall"] = round(radar_util['cpu'] / specs['cpu']['threads_total'], 2)




                # print("LiDAR:")
                # pprint.pprint(lidar_util)
                # print("\nCam:")
                # pprint.pprint(camera_util)
                # print("\nGPS:")
                # pprint.pprint(gps_util)
                # print("\nRadar:")
                # pprint.pprint(radar_util)

                metrics, dccs = compute_dccs()
                dccs_r = round(dccs * 100, 2)/100

                ros_snapshot = sensor_monitor.snapshot_sensors()
                # print("ROS Snapshot")
                # pprint.pprint(ros_snapshot)
                # print("spin alive:", spin_thread.is_alive())

                log_sensors(SESSION_STAMP, metrics=metrics, dccs=dccs_r, lidar=lidar_util, camera=camera_util, gps=gps_util, radar=radar_util,
                            ros_camera=ros_snapshot["cam"], ros_lidar=ros_snapshot["lidar"])
                
                pass
            except psutil.Error as e:
                print("Error", e)

            time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        sensor_monitor.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
Install turbostat

sudo apt update
sudo apt install linux-cpupower

## Setup

Make the energy file readable to avoid using sudo every time you need to launch
```bash
sudo chmod o+r /sys/class/powercap/intel-rapl:0/energy_uj
```

## DCCS Framework

## Usage
Run `pid.py` to start recording the processes per PID; this is for the real sensors
```bash
bash -c "source /opt/ros/humble/setup.bash && /home/autodrive/Desktop/DCCS/venv/bin/python /home/autodrive/Desktop/DCCS/src/pid.py"
```

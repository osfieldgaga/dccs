import psutil
import time


## Sanity tests for psutil

dt = 0
last_dt = 0

while True:
    dt = time.monotonic_ns()

    if (dt - last_dt > 1000000000):
        last_dt = dt

        print(psutil.cpu_percent(interval=1))
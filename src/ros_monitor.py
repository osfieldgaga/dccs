import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, Image
import time
import threading

class SensorMonitor(Node):
    def __init__(self):
        super().__init__("dccs_sensor_monitor")
        

        self.lidar_subscriber = self.create_subscription(PointCloud2, 
                                                         topic="/cepton_pcl2",
                                                         qos_profile=qos_profile_sensor_data,
                                                         callback=self.lidar_callback)
        
        self.cam_subscriber = self.create_subscription(Image, 
                                                       topic="/flir_camera/image_raw",
                                                       qos_profile=qos_profile_sensor_data,
                                                       callback=self.cam_callback)


        # self._lidar_start_time = time.monotonic_ns()
        self._lidar_last_dt = None
        self._lidar_last_stamp = None
        self._cam_last_dt = None
        self._lock = threading.Lock()

        # LiDAR values
        self.lidar = {
            "sensor_stamp_ns": None,
            "width": None,
            "height": None,
            "npts": None,
            "pt_step": None,
            "cloud_size_bytes": None,
            "is_dense": None,
            "hz_stamp": None,
            "hz": None,
        }

        # Camera values
        self.cam = {
            "sensor_stamp_ns": None,
            "width": None,
            "height": None,
            "npixels": None,          # width * height
            "encoding": None,         # e.g. "rgb8", "mono8", "bayer_rggb8"
            "step": None,             # bytes per row
            "is_bigendian": None,
            "img_size_bytes": None,   # len(msg.data), should equal step * height
            "hz_stamp": None,
            "hz": None,
        }
        

        self.get_logger().info("DCCS Sensor Monitor up.")

    def lidar_callback(self, msg: PointCloud2):
        now = time.monotonic_ns()
        now_stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

        if self._lidar_last_dt is not None and self._lidar_last_stamp is not None:
            period_ns = now - self._lidar_last_dt
            stamp_period_ns = now_stamp_ns - self._lidar_last_stamp

            with self._lock:
                self.lidar.update({
                    "sensor_stamp_ns": now_stamp_ns,
                    "width": msg.width,
                    "height": msg.height,
                    "npts": msg.width * msg.height,
                    "pt_step": msg.point_step,
                    "cloud_size_bytes": len(msg.data),
                    "is_dense": msg.is_dense,
                    "hz": round(1e9 / period_ns, 2) if period_ns > 0 else None,
                    "hz_stamp": round(1e9 / stamp_period_ns, 2) if stamp_period_ns > 0 else None,
                })


        self._lidar_last_dt = now
        self._lidar_last_stamp = now_stamp_ns


    def cam_callback(self, msg: Image):
        now = time.monotonic_ns()
        now_stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

        if self._cam_last_dt is not None and self._cam_last_stamp is not None:
            period_ns = now - self._cam_last_dt
            stamp_period_ns = now_stamp_ns - self._cam_last_stamp

            with self._lock:
                self.cam.update({
                    "sensor_stamp_ns": now_stamp_ns,
                    "width": msg.width,
                    "height": msg.height,
                    "npixels": msg.width * msg.height,
                    "encoding": msg.encoding,
                    "step": msg.step,
                    "is_bigendian": msg.is_bigendian,
                    "img_size_bytes": len(msg.data),
                    "hz": round(1e9 / period_ns, 2) if period_ns > 0 else None,
                    "hz_stamp": round(1e9 / stamp_period_ns, 2) if stamp_period_ns > 0 else None,
                })

        self._cam_last_dt = now
        self._cam_last_stamp = now_stamp_ns


    def snapshot_sensors(self):
        with self._lock:
            return {
                "lidar": dict(self.lidar),
                "cam": dict(self.cam),
            }


def main(args=None):
    rclpy.init(args=args)

    sensor_monitor = SensorMonitor()

    rclpy.spin(sensor_monitor)

    rclpy.shutdown()

if __name__ == "__main__":
    main()
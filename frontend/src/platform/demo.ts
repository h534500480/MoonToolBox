// 功能说明：复用 platform 遥测公式；演示状态与真实 ROS 状态完全隔离。
import { reactive } from "vue";
export const demoTopics = reactive(
  [
    ["/livox/lidar", "sensor_msgs/PointCloud2"],
    ["/ndt_pose", "geometry_msgs/PoseStamped"],
    ["/plan", "nav_msgs/Path"],
    ["/tf", "tf2_msgs/TFMessage"],
    ["/cmd_vel", "geometry_msgs/Twist"],
    ["/odometry/filtered", "nav_msgs/Odometry"],
    ["/battery", "sensor_msgs/BatteryState"],
    ["/joint_states", "sensor_msgs/JointState"],
    ["/score", "std_msgs/Float64"],
    ["/manual_relocalization_status", "std_msgs/String"],
    ["/nav_ndt_status", "std_msgs/String"],
  ].map(([key, type]) => ({ key, type, label: key, note: "" })),
);
export const demoData = reactive({
  pose: { x: -2.221, y: -0.084, z: -0.418, yaw: -0.074 },
  battery: 78,
  speed: 0.42,
  score: 0.925,
  values: {} as Record<string, any>,
  history: {} as Record<string, number[]>,
});
let time = 0;
/** 只由演示组件的生命周期计时器调用，离开演示后停止。 */
export function tickDemo() {
  time += 0.5;
  const phi = -1.6448 + 0.12 * time;
  const pose = {
    x: -1.962 + 3.5 * Math.cos(phi),
    y: 3.407 + 3.5 * Math.sin(phi),
    z: -0.418 + Math.sin(time) * 0.004,
    yaw: phi + Math.PI / 2,
  };
  demoData.pose = pose;
  demoData.battery = Math.max(5, 78 - time * 0.004);
  demoData.speed = 0.42 + Math.sin(time * 0.7) * 0.03;
  demoData.score = 0.925 + Math.sin(time * 0.35) * 0.018;
  Object.assign(demoData.values, {
    "/ndt_pose": pose,
    "/score": demoData.score,
    "/manual_relocalization_status": { data: "success" },
    "/battery": { percentage: demoData.battery, voltage: 29.1, current: 3.2 },
    "/cmd_vel": {
      linear: { x: demoData.speed, y: 0, z: 0 },
      angular: { z: 0.12 },
    },
    "/livox/lidar": {
      frame: "livox_frame",
      width: 118000,
      height: 1,
      pointStep: 22,
    },
    "/joint_states": {
      position: Array.from(
        { length: 12 },
        (_, i) => Math.sin(time * 6 + i) * 0.4,
      ),
    },
    "/odometry/filtered": { pose, twist: { linear: { x: demoData.speed } } },
    "/plan": { frame: "map", length: 3.36 },
    "/tf": {
      transforms: [{ parent: "map", child: "base_link", translation: pose }],
    },
  });
  for (const topic of demoTopics) {
    const value =
      topic.key === "/ndt_pose"
        ? pose.x
        : topic.key === "/score"
          ? demoData.score
          : demoData.speed;
    demoData.history[topic.key] = [
      ...(demoData.history[topic.key] || []),
      value,
    ].slice(-60);
  }
}

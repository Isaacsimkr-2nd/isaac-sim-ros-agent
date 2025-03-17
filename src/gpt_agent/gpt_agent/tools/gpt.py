#!/usr/bin/env python3
import threading
import time
import logging
import math

import rclpy
from rclpy.node import Node

from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from yolo_perception.msg import DetectionArray, DetectionInfo

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CustomRobotNode(Node):
    def __init__(self):
        super().__init__("custom_robot_node")
        self.current_position = (0.0, 0.0, 0.0)  # (x, y, yaw)
        self.odom_received = False
        self.deviance = 0

        # 목표 위치 (GPT가 활용할 수 있도록 보관만 함)
        self.target_x = None
        self.target_y = None

        # 이동 제어용 플래그, 속도, 시간 변수
        self.move_flag = False
        self.move_start_time = 0.0
        self.move_duration = 0.0
        self.cur_linear_x = 0.0
        self.cur_angular_z = 0.0

        # Subscriber & Publisher
        self.odom_sub = self.create_subscription(
            Odometry, "/odom", self.odom_callback, 10
        )
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        # YOLO 감지 관련
        self.detection_result = []
        self.yolo_sub = self.create_subscription(
            DetectionArray,
            '/detection_results',
            self.yolo_callback,
            10
        )

        # 주기적으로 cmd_vel 제어하는 타이머 (0.01초마다)
        self.timer = self.create_timer(0.01, self.cmd_vel_timer_cb)

        self.get_logger().info("CustomRobotNode initialized.")
        logger.info("CustomRobotNode 생성됨")

    def odom_callback(self, msg: Odometry):
        """Odometry 메시지를 받아 현재 위치와 방향을 업데이트."""
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        qx = msg.pose.pose.orientation.x
        qy = msg.pose.pose.orientation.y
        qz = msg.pose.pose.orientation.z
        qw = msg.pose.pose.orientation.w

        # Quaternion -> Yaw 변환
        yaw = math.atan2(
            2 * (qw * qz + qx * qy),
            1 - 2 * (qy**2 + qz**2)
        )

        self.current_position = (x, y, yaw)
        self.odom_received = True

    def yolo_callback(self, msg):
        """
        YOLO 감지 결과 콜백 함수
        """
        self.detection_result = msg.detections  # DetectionInfo[] 형태
        
        # 예시로, 첫 번째 DetectionInfo만 사용해 deviance 계산
        if len(self.detection_result) > 0:
            bb = self.detection_result[0].bounding_box
            # bounding_box = [x1, y1, x2, y2]
            center_x = (bb[0] + bb[2]) / 2
            self.deviance = 640 - center_x
        else:
            self.deviance = 0

    def set_target_position(self, target_x: float, target_y: float):
        """목표 위치를 저장만 함 (실제 이동은 move_to_position에서 제어)."""
        self.target_x = target_x
        self.target_y = target_y
        self.get_logger().info(f"목표 위치 설정: ({target_x:.2f}, {target_y:.2f})")

    def error_calculate(self) -> dict:
        """
        목표 위치( self.target_x, self.target_y )로부터의 거리/각도 오차 계산.
        """
        if self.target_x is None or self.target_y is None:
            return {"distance_error": 0.0, "angle_error": 0.0}

        x, y, yaw = self.current_position
        dx = self.target_x - x
        dy = self.target_y - y
        distance = math.sqrt(dx**2 + dy**2)

        # 목표 각도 계산
        target_angle = math.atan2(dy, dx)
        angle_error = (target_angle - yaw + 2 * math.pi) % (2 * math.pi)
        if angle_error > math.pi:
            angle_error -= 2 * math.pi

        return {
            "distance_error": distance,
            "angle_error": angle_error
        }

    def publish_twist_to_cmd_vel(self, linear_x: float, angular_z: float, duration: float):
        """
        이동 플래그 방식으로 선/각속도 및 이동 시간 설정.
        (이제 즉시 time.sleep()과 정지명령을 내리지 않음)
        """
        self.cur_linear_x = linear_x
        self.cur_angular_z = angular_z
        self.move_duration = duration
        self.move_start_time = time.time()
        self.move_flag = True

        return (f"Twist 명령: linear_x={linear_x}, angular_z={angular_z}, "
                f"duration={duration}")

    def cmd_vel_timer_cb(self):
        """
        주기적 타이머 콜백. move_flag가 True면 duration 확인하여 Twist 발행.
        duration이 끝나면 정지.
        """
        if self.move_flag:
            elapsed = time.time() - self.move_start_time
            if elapsed < self.move_duration:
                # 아직 이동 중
                twist = Twist()
                twist.linear.x = self.cur_linear_x
                twist.angular.z = self.cur_angular_z
                self.cmd_vel_pub.publish(twist)
            else:
                # duration 경과 -> 정지
                self.cmd_vel_pub.publish(Twist())
                self.move_flag = False

# -----------------------------
# 전역 노드 관리 함수
# -----------------------------
_robot_node: CustomRobotNode = None
_ros_thread = None
_initialized = False

def _get_robot_node() -> CustomRobotNode:
    """
    로봇 노드를 초기화하고, 싱글턴 형태로 반환.
    최초 한 번만 rclpy.init()을 호출하고, 이후에는 같은 노드를 재사용.
    """
    global _robot_node, _ros_thread, _initialized
    if _robot_node is None:
        if not _initialized:
            logger.info("ROS2 초기화 시작")
            rclpy.init(args=None)
            _initialized = True

        _robot_node = CustomRobotNode()

        def ros_spin():
            try:
                rclpy.spin(_robot_node)
            except Exception as e:
                logger.error(f"ROS2 스핀 오류: {str(e)}")

        _ros_thread = threading.Thread(target=ros_spin, daemon=True)
        _ros_thread.start()

        # Odometry 초기 수신 대기 (최대 3초)
        timeout = 3.0
        start_time = time.time()
        while time.time() - start_time < timeout:
            if _robot_node.odom_received:
                logger.info("Odometry 데이터 수신 확인")
                break
            time.sleep(0.1)
        else:
            logger.warning("Odometry 데이터 수신 대기 시간 초과")

        logger.info("ROS2 노드 초기화 완료")

    return _robot_node

# --------------------------------
# LangChain 도구 함수
# --------------------------------
from langchain.agents import tool

@tool
def get_robot_pose() -> str:
    """
    로봇의 현재 위치를 반환.
    x, y, yaw (라디안 단위).
    """
    try:
        agent = _get_robot_node()
        x, y, yaw = agent.current_position
        if not agent.odom_received:
            logger.warning("Odometry 데이터 미수신")
            return "현재 위치: 데이터 없음 (odom 미수신)"
        return f"현재 위치: x={x:.2f}m, y={y:.2f}m, yaw={yaw:.2f}rad"
    except Exception as e:
        logger.error(f"위치 조회 오류: {str(e)}")
        return f"위치 조회 오류: {str(e)}"


@tool
def move_to_position(target_x: float, target_y: float, target_yaw: float) -> str:
    """
    예: 목표 위치 (target_x, target_y)까지 이동한 뒤, target_yaw까지 회전.
    내부에서 반복적으로 distance_error, angle_error를 계산하여 publish_twist_to_cmd_vel() 호출.
    """
    agent = _get_robot_node()
    agent.set_target_position(target_x, target_y)

    # 1) 목표 위치까지 이동
    while True:
        errors = agent.error_calculate()
        distance = errors["distance_error"]
        angle_err = errors["angle_error"]

        # --- 도착 판정 ---
        if distance < 0.05:
            agent.move_flag = False  # 이동 중지
            agent.cmd_vel_pub.publish(Twist())  # 즉시 정지
            break

        # 거리 비례 제어로 선속도 결정 (0.05 ~ 0.3 사이)
        linear_speed = min(0.3, max(0.05, distance * 2))
        # 각속도 결정: angle_err * 2 (클램핑: -1.0 ~ 1.0)
        angular_speed = max(-1.0, min(1.0, angle_err * 2))

        # 짧은 시간(예: 0.05초)만큼 이동 명령
        agent.publish_twist_to_cmd_vel(linear_speed, angular_speed, 0.05)
        time.sleep(0.05)  # 이동 명령 갱신 간격

    # 2) 목표 각도 회전
    while True:
        x, y, yaw = agent.current_position
        error = target_yaw - yaw
        error = (error + math.pi) % (2 * math.pi) - math.pi  # -π ~ π로 보정

        if abs(error) < 0.1:
            agent.move_flag = False
            agent.cmd_vel_pub.publish(Twist())  # 즉시 정지
            return (f"이동 및 회전 완료: "
                    f"목표 위치 ({target_x:.2f}, {target_y:.2f}), "
                    f"목표 각도 {target_yaw:.2f} rad 도달.")

        angular_speed = max(-1.0, min(1.0, error * 2))
        agent.publish_twist_to_cmd_vel(0.0, angular_speed, 0.1)
        time.sleep(0.1)


@tool 
def yolo_tool():
    """
    카메라 피드를 기반으로 객체를 감지합니다.
    전방에 무엇이 보이는지 확인하고 싶을 때 해당 도구를 사용하세요.
    deviance는 로봇 기준 편차값(640픽셀 - 감지된 x중심).
    """
    agent = _get_robot_node()

    results = []
    for detection in agent.detection_result:
        data = {
            "label": detection.label,
            "confidence": detection.confidence,
            "bounding_box": list(detection.bounding_box),
            "width": detection.width,
            "height": detection.height,
        }
        results.append(data)

    return results


@tool
def face_detection(target_yaw: float) -> str:
    """
    예: 정면을 바라보게 회전하는 명령을 수행.
    deviance(픽셀 단위 편차)에 따라 회전값 조정.
    """
    agent = _get_robot_node()

    while True:
        x, y, yaw = agent.current_position
        error = agent.deviance

        # 에러가 작으면 정지
        if abs(error) < 10:
            agent.move_flag = False
            agent.cmd_vel_pub.publish(Twist())  # 정지
            return (f"정면({target_yaw:.2f} rad) 바라봄")

        logger.info(f"편차: {error}")
        angular_speed = max(-1.0, min(1.0, error * 0.01))
        agent.publish_twist_to_cmd_vel(0.0, angular_speed, 0.01)
        time.sleep(0.01)


@tool
def move_detection(linear_x: float, angular_z: float, duration: float) -> str:
    """
    예: 대상으로 부터 멀리 떨어지거나, 가까이 다가가는 동작을 수행.
    """
    agent = _get_robot_node()
    start_time = time.time()

    while True:
        x, y, yaw = agent.current_position
        if (time.time()- start_time) > duration:
            agent.move_flag = False
            agent.cmd_vel_pub.publish(Twist())  # 정지
            return (f"이동 완료")
        
        agent.publish_twist_to_cmd_vel(linear_x, angular_z, 0.01)
        time.sleep(0.01)


# --------------------------------
# 실행 함수
# --------------------------------
def main():
    node = _get_robot_node()
    try:
        # 노드가 종료될 때까지 대기
        while rclpy.ok():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("종료 요청 수신됨")
    finally:
        if node is not None:
            node.destroy_node()
        if _initialized:
            rclpy.shutdown()
        if _ros_thread is not None:
            _ros_thread.join(timeout=1.0)
            logger.info("ROS2 스레드 종료")

if __name__ == "__main__":
    main()

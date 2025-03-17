#!/usr/bin/env python3
import threading
import time
import logging
import math

import rclpy
from rclpy.node import Node

from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CustomRobotNode(Node):
    def __init__(self):
        super().__init__("custom_robot_node")
        self.current_position = (0.0, 0.0, 0.0)  # (x, y, yaw)
        self.odom_received = False

        # 목표 위치 관련 플래그
        self.moving_to_target = False
        self.target_x = None
        self.target_y = None

        # Subscriber & Publisher
        self.odom_sub = self.create_subscription(
            Odometry, "/odom", self.odom_callback, 10
        )
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        # 0.01초마다 제어 콜백
        self.timer = self.create_timer(0.01, self.timer_callback)

        self.get_logger().info("CustomRobotNode initialized.")
        logger.info("CustomRobotNode 생성됨")

    def odom_callback(self, msg: Odometry):
        """Odometry 메시지를 받아 현재 위치와 방향을 업데이트"""
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

    def timer_callback(self):
        """주기적으로 로봇 이동 제어"""
        if self.moving_to_target:
            self.move_to_target()

    def move_to_target(self):
        """
        목표 위치로 이동하는 로직 (회전과 이동 동시 수행)
        매 주기(timer_callback)마다 호출되며,
        거리가 충분히 작아지면 이동을 멈춥니다.
        """
        x, y, yaw = self.current_position
        dx = self.target_x - x
        dy = self.target_y - y
        distance = math.sqrt(dx**2 + dy**2)

        # --- 1) 도착 판정 ---
        if distance < 0.05:
            # 목표 위치 근처면 정지
            self.moving_to_target = False
            self.cmd_vel_pub.publish(Twist())  # 정지
            self.get_logger().info(
                f"목표 위치 도달: ({self.target_x:.2f}, {self.target_y:.2f})"
            )
            return

        # --- 2) 회전(각도) 오차 계산 ---
        target_angle = math.atan2(dy, dx)
        error = (target_angle - yaw + 2 * math.pi) % (2 * math.pi)
        if error > math.pi:
            error -= 2 * math.pi

        # --- 3) 선속도 & 각속도 결정 ---
        # distance * 2 -> 거리 비례제어 (최대 0.3 m/s)
        # 너무 작은 값은 무시되지 않도록 최소 속도 0.05 m/s 보장
        linear_speed = min(0.3, max(0.05, distance * 2))
        angular_speed = min(1.0, max(-1.0, error * 2))

        twist = Twist()
        twist.linear.x = linear_speed
        twist.angular.z = angular_speed
        self.cmd_vel_pub.publish(twist)

    def set_target_position(self, target_x: float, target_y: float):
        """목표 위치 설정"""
        self.target_x = target_x
        self.target_y = target_y
        self.moving_to_target = True
        self.get_logger().info(f"목표 위치 설정: ({target_x:.2f}, {target_y:.2f})")

    def publish_twist_to_cmd_vel(self, linear_x: float, angular_z: float, duration: float):
        """
        linear_x, angular_z로 duration동안 이동 명령을 수행한 뒤 정지.
        매우 짧은 시간을 주면 물리적으로 움직이지 않을 수 있으므로
        최소 0.1초 이상 부여를 권장.
        """
        twist = Twist()
        twist.linear.x = linear_x
        twist.angular.z = angular_z
        self.cmd_vel_pub.publish(twist)

        # 실제 바퀴가 돌 기회를 주기 위해 잠시 대기
        time.sleep(duration)

        # 정지
        self.cmd_vel_pub.publish(Twist())
        return f"Twist 메시지 게시: linear_x={linear_x}, angular_z={angular_z}, duration={duration}"

# 전역 노드 관리
_robot_node: CustomRobotNode = None
_ros_thread = None
_initialized = False

def _get_robot_node() -> CustomRobotNode:
    """로봇 노드 초기화 및 반환"""
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

# LangChain 도구 함수 (필요 없다면 그대로 사용 안 해도 됨)
from langchain.agents import tool

@tool
def get_robot_pose() -> str:
    """로봇의 현재 위치 반환"""
    try:
        agent = _get_robot_node()
        x, y, yaw = agent.current_position
        if not agent.odom_received:
            logger.warning("Odometry 데이터 미수신")
            return "현재 위치: 데이터 없음 (/odom 토픽 확인 필요)"
        return f"현재 위치: x={x:.2f}m, y={y:.2f}m, yaw={yaw:.2f}rad"
    except Exception as e:
        logger.error(f"위치 조회 오류: {str(e)}")
        return f"위치 조회 오류: {str(e)}"

@tool
def move_to_position(target_x: float, target_y: float, target_yaw: float) -> str:
    """
    목표 위치로 로봇 이동 후 목표 각도(target_yaw)까지 회전.
    오차 범위(약 0.05m 이내)에 들면 자동으로 정지하고, 이후 회전을 수행합니다.
    """
    agent = _get_robot_node()
    agent.set_target_position(target_x, target_y)

    # 이동 완료 대기
    while agent.moving_to_target:
        time.sleep(0.1)

    # 위치 도착 후 회전 수행
    while True:
        # 현재 위치 정보 가져오기
        x, y, yaw = agent.current_position
        
        # 목표 각도와 현재 각도의 차이 계산 (범위: -π ~ π)
        error = target_yaw - yaw
        error = (error + math.pi) % (2 * math.pi) - math.pi  # -π ~ π로 보정

        # 임계값 이하이면 회전 중지
        if abs(error) < 0.1:
            agent.cmd_vel_pub.publish(Twist())  # 정지 명령
            return f"이동 및 회전 완료: 목표 위치 ({target_x:.2f}, {target_y:.2f}), 목표 각도 {target_yaw:.2f} rad 도달."

        # 회전 속도 결정 (비례 제어)
        angular_speed = max(-1.0, min(1.0, error * 2))

        # Twist 메시지 발행
        twist = Twist()
        twist.angular.z = angular_speed
        agent.cmd_vel_pub.publish(twist)

        # 주기적으로 확인 (10ms)
        time.sleep(0.01)


# 실행 함수
def main():
    node = _get_robot_node()
    try:
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

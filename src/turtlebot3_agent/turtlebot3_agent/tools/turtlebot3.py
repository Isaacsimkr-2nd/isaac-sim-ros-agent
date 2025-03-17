#!/usr/bin/env python3
import threading
import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from langchain.agents import tool
from ultralytics import YOLO

# odometry 추가
from nav_msgs.msg import Odometry
import math

# 커스텀 메시지: yolo_perception/msg/DetectionArray, DetectionInfo
from yolo_perception.msg import DetectionArray, DetectionInfo


import cv2 

class TurtleBot3Agent(Node):
    def __init__(self):
        super().__init__('turtlebot3_agent_tools')

        # /cmd_vel 퍼블리셔 생성
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        # 이동 관련 변수
        self.move_flag = False
        self.start_time = None
        self.duration = 0.0
        self.linear = 0.0
        self.angular = 0.0
        self.current_position = (0.0, 0.0, 0.0)  # (x, y, yaw)

        # YOLO 감지 관련
        self.detection_result = []
        self.yolo_received = False  # 한 번만 감지 결과를 저장하기 위한 플래그

        # 주기적으로 이동 상태 확인 (0.1초마다 실행)
        self.timer = self.create_timer(0.1, self.timer_callback)

        # odometry 추가
        self.odom_sub = self.create_subscription(Odometry, '/odom', self.odom_callback, 10)

        # 1) DetectionArray를 구독하여 한 번만 감지 결과를 저장
        self.yolo_sub = self.create_subscription(
            DetectionArray,
            '/detection_results',     # 사용자가 원하는 토픽 이름
            self.yolo_callback,
            10
        )

    def timer_callback(self):
        """
        이동 상태를 주기적으로 확인하여 duration이 지나면 정지
        """
        if self.move_flag:
            current_time = self.get_clock().now()
            elapsed = (current_time - self.start_time).nanoseconds / 1e9  # 초 단위 변환

            if elapsed < self.duration:
                twist_msg = Twist()
                twist_msg.linear.x = self.linear
                twist_msg.angular.z = self.angular
                self.cmd_vel_pub.publish(twist_msg)
            else:
                self.get_logger().info("이동 시간 초과: 정지")
                self.move_flag = False  # 이동 중지
                self.stop_movement()

    def stop_movement(self):
        """
        즉시 정지 명령을 실행
        """
        stop_msg = Twist()
        self.cmd_vel_pub.publish(stop_msg)
        self.get_logger().info("즉시 정지")

    def publish_twist_to_cmd_vel(self, velocity: float, angle: float, duration: float = 1.0) -> str:
        self.linear = velocity
        self.angular = angle
        self.duration = duration
        self.start_time = self.get_clock().now()
        self.move_flag = True  # 이동 시작

        return f"turtlebot3 이동 명령: velocity={velocity}, angle={angle}, duration={duration}s."

    def stop_turtlebot3(self) -> str:
        self.move_flag = False
        self.stop_movement()
        return "turtlebot3 즉시 정지 명령 실행됨."

    def odom_callback(self, msg):
        """
        odometry 메시지 콜백 함수
        """
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y

        # 쿼터니언 -> 오일러 각도 변환
        qx = msg.pose.pose.orientation.x
        qy = msg.pose.pose.orientation.y
        qz = msg.pose.pose.orientation.z
        qw = msg.pose.pose.orientation.w
        yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy**2 + qz**2))
        self.current_position = (x, y, yaw)

    def yolo_callback(self, msg):
        """
        YOLO 감지 결과 콜백 함수
        - 한 번만(self.yolo_received == False 일 때만) 감지 결과를 저장
        """
        # if not self.yolo_received:
        # self.get_logger().info(f"감지된 객체 수: {msg.count}")
        self.detection_result = msg.detections  # DetectionInfo[] 형태
        self.yolo_received = True


# 글로벌 인스턴스를 관리하여 LangChain과 연결
turtlebot3_agent = None
ros_thread = None

def get_turtlebot3_agent():
    global turtlebot3_agent, ros_thread

    if turtlebot3_agent is None:
        rclpy.init(args=None)
        turtlebot3_agent = TurtleBot3Agent()

        # ROS 2 노드를 별도 스레드에서 실행하여 LangChain과 동시 실행
        def ros_spin():
            rclpy.spin(turtlebot3_agent)

        ros_thread = threading.Thread(target=ros_spin, daemon=True)
        ros_thread.start()

    return turtlebot3_agent

@tool
def forward_or_backward(velocity: float, duration: float = 1.0) -> str:
    """
    [툴 함수] turtlebot3의 /cmd_vel 토픽에 Twist 메시지를 발행하여 전진 또는 후진 합니다.
    직전 전진 또는 직선 후진의 경우 angle는 0.0이고 velocity만 조정합니다. 
    이동 경과를 위해 odom을 사용합니다.
    
    :param velocity: 선속도 (m/s) (양수: 전진, 음수: 후진)
    :param duration: 이동 지속 시간 (초 단위)
    """
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(velocity, 0.0, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def rotate_in_place(angle: float = 0.1, duration: float = 0.1) -> str:
    """
    [툴 함수] turtlebot3의 /cmd_vel 토픽에 Twist 메시지를 발행하여 제자리 회전 합니다.
    회전인 경우 velocity는 0.0이고 angle만 조정합니다.
    이동 경과를 위해 odom을 사용합니다.
    
    
    :param angle: 각속도 (rad/s) (양수: 반시계 방향 회전, 음수: 시계 방향 회전)
    :param duration: 이동 지속 시간 (초 단위)
    """
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(0.0, angle, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def move_with_direction(velocity: float, angle: float, duration: float = 1.0) -> str:
    """
    [툴 함수] turtlebot3의 /cmd_vel 토픽에 Twist 메시지를 발행하여 방향성이 있는 전진 또는 후진 합니다.
    왼쪽으로 이동 또는 오른쪽으로 이동과 같이, '방향성이 있는 이동'인 경우 velocity와 angle을 모두 조정합니다.
    
    '왼쪽으로 이동'하는 경우 velocity와 angle이 모두 양수 입니다. 
    '오른쪽으로 이동'하는 경우 velocity는 양수 angle는 음수 입니다. 
    '~을 향해 이동'할때 사용합니다.
    
    :param velocity: 선속도 (m/s) (양수: 전진, 음수: 후진)
    :param angle: 각속도 (rad/s) (양수: 왼쪽 방향, 음수: 오른쪽 방향)
    :param duration: 이동 지속 시간 (초 단위)
    """
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(velocity, angle, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def stop_turtlebot3() -> str:
    """
    [툴 함수] turtlebot3를 즉시 정지시킵니다.
    """
    agent = get_turtlebot3_agent()
    return agent.stop_turtlebot3()

@tool
def get_turtlebot3_position() -> str:
    """
    [툴 함수] turtlebot3의 현재 위치를 반환합니다.
    x(m), y(m), yaw(rad) 형식으로 반환합니다.
    """
    agent = get_turtlebot3_agent()
    x, y, yaw = agent.current_position
    return f"현재 위치: x={x:.2f}m, y={y:.2f}m, yaw={yaw:.2f}rad"

@tool 
def yolo_tool():
    """
    카메라 피드를 기반으로 객체를 감지합니다.
    전방에 무엇이 보이는지 확인하고 싶을 때 해당 도구를 사용하세요.
    deviance는 사람과 로봇과의 상대적인 yaw 값 입니다 (절대적인 rad또는 degree 값이 아닙니다).
    """
    # 여기서는 실제로 카메라를 사용하지 않고,
    # 이미 구독된 DetectionArray (agent.detection_result)만 반환한다고 가정.
    agent = get_turtlebot3_agent()

    if not agent.yolo_received:
        return [{"error": "YOLO 감지가 아직 실행되지 않았거나 결과가 없습니다."}]

    # DetectionInfo[] 구조를 그대로 반환, 필요하다면 가공 가능
    results = []
    for detection in agent.detection_result:

        # detection: DetectionInfo
        data = {
            "label": detection.label,
            "confidence": detection.confidence,
            "bounding_box": list(detection.bounding_box),  # int32[] -> Python list
            "width": detection.width,
            "height": detection.height,
            "center_x":(list(detection.bounding_box)[0] + list(detection.bounding_box)[2]) / 2,
            "deviance" : 640 - (list(detection.bounding_box)[0] + list(detection.bounding_box)[2]) / 2
        }
        results.append(data)

    return results


@tool
def find_detection(velocity: float, angle: float, duration: float = 1.0) -> str:
    """
    [툴 함수] turtlebot3의 /cmd_vel 토픽에 Twist 메시지를 발행하여 움직입니다. 
    객체를 찾기 위해 turtlebot3는 움직입니다. 
    객체를 찾기 위해 제자리 회전하기도 하고 방향성 있는 이동을 하기도 합니다.  
    선속도 velocity와 각속도 angle를 통해 주변을 살피고 yolo_tool을 사용하여 객체를 찾습니다.
    무엇을 찾기 위해 사용됩니다.
    deviance 의 값을 기준으로 양수이면 cmd_vel의 angle 양수
    deviance 의 값을 기준으로 cmd_vel의 angle 음수 .
    """
    agent = get_turtlebot3_agent()
    detection_result = yolo_tool.invoke({})

    return agent.publish_twist_to_cmd_vel(velocity, angle, duration)

@tool
def face_detection(velocity: float, angle: float, duration: float = 1.0) -> str:
    """
    [툴 함수] 
    객체를 마주보기 위하여 이동합니다.. 
    객체의 정면을 마주보기 위하여 사용됩니다.
    deviance 의 값을 기준으로 양수이면 angle의 값은 -30 degrees, deviance 의 값이 음수이면 cmd_vel의 +30 degrees 입니다.
    """
    agent = get_turtlebot3_agent()
    detection_result = yolo_tool.invoke({})
    return_twist = agent.publish_twist_to_cmd_vel(velocity, angle, duration)
    return_detection = detection_result
    
    return return_twist+return_detection

# ROS 2 노드를 실행하는 메인 함수
def main(args=None):
    global turtlebot3_agent
    turtlebot3_agent = get_turtlebot3_agent()
    try:
        rclpy.spin(turtlebot3_agent)
    except KeyboardInterrupt:
        pass
    finally:
        turtlebot3_agent.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

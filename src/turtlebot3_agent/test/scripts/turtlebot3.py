#!/usr/bin/env python3
import threading
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from langchain.agents import tool
from nav_msgs.msg import Odometry
import math
from yolo_perception.msg import DetectionArray, DetectionInfo
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import os
import requests
import base64
import json
from dotenv import load_dotenv

class TurtleBot3Agent(Node):
    def __init__(self):
        super().__init__('turtlebot3_agent_tools')
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.move_flag = False
        self.start_time = None
        self.duration = 0.0
        self.linear = 0.0
        self.angular = 0.0
        self.current_position = (0.0, 0.0, 0.0)

        # YOLO 감지 관련
        self.detection_result = []
        self.yolo_received = False

        # GPT-4o-mini 관련
        load_dotenv()
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            self.get_logger().error('OPENAI_API_KEY가 설정되지 않았습니다!')
        self.image_path = '/tmp/turtlebot3_image.jpg'
        self.latest_image = None  # 최신 이미지 저장용
        self.bridge = CvBridge()

        self.timer = self.create_timer(0.1, self.timer_callback)
        self.odom_sub = self.create_subscription(Odometry, '/odom', self.odom_callback, 10)
        self.yolo_sub = self.create_subscription(DetectionArray, '/detection_results', self.yolo_callback, 10)
        self.image_sub = self.create_subscription(Image, '/demo_cam/camera1/image_raw', self.image_callback, 10)

    def timer_callback(self):
        if self.move_flag:
            current_time = self.get_clock().now()
            elapsed = (current_time - self.start_time).nanoseconds / 1e9
            if elapsed < self.duration:
                twist_msg = Twist()
                twist_msg.linear.x = self.linear
                twist_msg.angular.z = self.angular
                self.cmd_vel_pub.publish(twist_msg)
            else:
                self.get_logger().info("이동 시간 초과: 정지")
                self.move_flag = False
                self.stop_movement()

    def stop_movement(self):
        stop_msg = Twist()
        self.cmd_vel_pub.publish(stop_msg)
        self.get_logger().info("즉시 정지")

    def publish_twist_to_cmd_vel(self, velocity: float, angle: float, duration: float = 1.0) -> str:
        self.linear = velocity
        self.angular = angle
        self.duration = duration
        self.start_time = self.get_clock().now()
        self.move_flag = True
        return f"turtlebot3 이동 명령: velocity={velocity}, angle={angle}, duration={duration}s."

    def stop_turtlebot3(self) -> str:
        self.move_flag = False
        self.stop_movement()
        return "turtlebot3 즉시 정지 명령 실행됨."

    def odom_callback(self, msg):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        qx, qy, qz, qw = msg.pose.pose.orientation.x, msg.pose.pose.orientation.y, msg.pose.pose.orientation.z, msg.pose.pose.orientation.w
        yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy**2 + qz**2))
        self.current_position = (x, y, yaw)

    def yolo_callback(self, msg):
        self.detection_result = msg.detections
        self.yolo_received = True

    def image_callback(self, msg):
        """최신 이미지를 계속 저장"""
        self.latest_image = msg  # 최신 이미지 메시지를 저장

    def analyze_with_gpt(self, image_msg):
        """GPT-4o-mini로 이미지 분석"""
        if image_msg is None:
            return "이미지가 아직 수신되지 않았습니다."
        
        # ROS 이미지 -> OpenCV 이미지 변환 및 저장
        cv_image = self.bridge.imgmsg_to_cv2(image_msg, desired_encoding='bgr8')
        cv2.imwrite(self.image_path, cv_image)
        self.get_logger().info(f'이미지가 {self.image_path}에 저장되었습니다.')

        with open(self.image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "이 이미지에 무엇이 있는지 설명해주세요."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}]}
            ],
            "max_tokens": 300
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            self.get_logger().error(f'GPT API 호출 실패: {response.status_code}, {response.text}')
            return f"GPT 분석 실패: {response.status_code}"

# 글로벌 인스턴스 관리
turtlebot3_agent = None
ros_thread = None

def get_turtlebot3_agent():
    global turtlebot3_agent, ros_thread
    if turtlebot3_agent is None:
        rclpy.init(args=None)
        turtlebot3_agent = TurtleBot3Agent()
        def ros_spin():
            rclpy.spin(turtlebot3_agent)
        ros_thread = threading.Thread(target=ros_spin, daemon=True)
        ros_thread.start()
    return turtlebot3_agent

@tool
def forward_or_backward(velocity: float, duration: float = 1.0) -> str:
    """TurtleBot3를 전진 또는 후진 시킵니다.
    :param velocity: 선속도 (m/s, 양수: 전진, 음수: 후진)
    :param duration: 이동 지속 시간 (초 단위)
    :return: 이동 명령과 현재 위치"""
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(velocity, 0.0, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def rotate_in_place(angle: float = 0.1, duration: float = 0.1) -> str:
    """TurtleBot3를 제자리에서 회전시킵니다.
    :param angle: 각속도 (rad/s, 양수: 반시계, 음수: 시계)
    :param duration: 이동 지속 시간 (초 단위)
    :return: 이동 명령과 현재 위치"""
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(0.0, angle, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def move_with_direction(velocity: float, angle: float, duration: float = 1.0) -> str:
    """TurtleBot3를 방향성 있게 이동시킵니다.
    :param velocity: 선속도 (m/s, 양수: 전진, 음수: 후진)
    :param angle: 각속도 (rad/s, 양수: 왼쪽, 음수: 오른쪽)
    :param duration: 이동 지속 시간 (초 단위)
    :return: 이동 명령과 현재 위치"""
    agent = get_turtlebot3_agent()
    pub_cmd = agent.publish_twist_to_cmd_vel(velocity, angle, duration)
    odom = agent.current_position
    return f"{pub_cmd} 현재 위치: x={odom[0]:.2f}m, y={odom[1]:.2f}m, yaw={odom[2]:.2f}rad"

@tool
def stop_turtlebot3() -> str:
    """TurtleBot3를 즉시 정지시킵니다.
    :return: 정지 명령 결과"""
    agent = get_turtlebot3_agent()
    return agent.stop_turtlebot3()

@tool
def get_turtlebot3_position() -> str:
    """TurtleBot3의 현재 위치를 반환합니다.
    :return: x, y, yaw 값"""
    agent = get_turtlebot3_agent()
    x, y, yaw = agent.current_position
    return f"현재 위치: x={x:.2f}m, y={y:.2f}m, yaw={yaw:.2f}rad"

@tool
def yolo_tool() -> list:
    """카메라 피드를 기반으로 객체를 감지합니다.
    :return: 감지된 객체 리스트"""
    agent = get_turtlebot3_agent()
    if not agent.yolo_received:
        return [{"error": "YOLO 감지가 아직 실행되지 않았거나 결과가 없습니다."}]
    results = []
    for detection in agent.detection_result:
        data = {
            "label": detection.label,
            "confidence": detection.confidence,
            "bounding_box": list(detection.bounding_box),
            "width": detection.width,
            "height": detection.height,
            "center_x": (list(detection.bounding_box)[0] + list(detection.bounding_box)[2]) / 2,
            "deviance": 640 - (list(detection.bounding_box)[0] + list(detection.bounding_box)[2]) / 2
        }
        results.append(data)
    return results

@tool
def find_detection(velocity: float, angle: float, duration: float = 1.0) -> str:
    """객체를 찾기 위해 TurtleBot3를 이동시킵니다.
    :param velocity: 선속도 (m/s)
    :param angle: 각속도 (rad/s)
    :param duration: 이동 지속 시간 (초 단위)
    :return: 이동 명령"""
    agent = get_turtlebot3_agent()
    yolo_tool.invoke({})
    return agent.publish_twist_to_cmd_vel(velocity, angle, duration)

@tool
def face_detection(velocity: float, angle: float, duration: float = 1.0) -> str:
    """객체의 정면을 마주보기 위해 TurtleBot3를 회전시킵니다.
    :param velocity: 선속도 (m/s)
    :param angle: 각속도 (rad/s)
    :param duration: 이동 지속 시간 (초 단위)
    :return: 이동 명령과 감지 결과"""
    agent = get_turtlebot3_agent()
    detection_result = yolo_tool.invoke({})
    return_twist = agent.publish_twist_to_cmd_vel(velocity, angle, duration)
    return return_twist + str(detection_result)

@tool
def describe_scene_with_gpt() -> str:
    """카메라 이미지를 GPT-4o-mini로 분석하여 장면을 설명합니다.
    :return: GPT 분석 결과"""
    agent = get_turtlebot3_agent()
    if agent.latest_image is None:
        return "이미지가 아직 수신되지 않았습니다. 카메라를 확인해주세요."
    result = agent.analyze_with_gpt(agent.latest_image)
    return f"GPT-4o-mini 분석 결과: {result}"

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
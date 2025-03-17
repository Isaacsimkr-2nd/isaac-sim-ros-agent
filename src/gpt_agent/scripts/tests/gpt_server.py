import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import os
import requests
import base64
import json
from dotenv import load_dotenv
from std_srvs.srv import Trigger  # ROS2 서비스 타입

class ImageAnalyzerService(Node):
    def __init__(self):
        super().__init__('image_analyzer_service')
        
        # 환경 변수 로드
        load_dotenv()
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            self.get_logger().error('OPENAI_API_KEY가 설정되지 않았습니다!')
            return

        # ROS2 서비스 서버 생성
        self.srv = self.create_service(Trigger, 'analyze_image', self.handle_request)
        
        # ROS2 이미지 토픽 구독
        self.subscription = self.create_subscription(
            Image,
            '/camera_color_frame/image_raw',
            self.image_callback,
            10)
        
        self.bridge = CvBridge()
        self.image_path = '/tmp/image.jpg'
        self.latest_image = None  # 최신 이미지 저장

    def image_callback(self, msg):
        """이미지를 저장하고 클라이언트 요청을 기다림"""
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            cv2.imwrite(self.image_path, cv_image)
            self.latest_image = self.image_path
            self.get_logger().info(f'이미지가 {self.image_path}에 저장되었습니다.')
        except Exception as e:
            self.get_logger().error(f'이미지 저장 실패: {str(e)}')

    def handle_request(self, request, response):
        """서비스 요청이 오면 이미지 분석 수행"""
        if not self.latest_image:
            response.success = False
            response.message = "저장된 이미지가 없습니다."
            return response

        analysis = self.analyze_image_with_chatgpt(self.latest_image)
        if analysis:
            response.success = True
            response.message = analysis
        else:
            response.success = False
            response.message = "이미지 분석 실패"
        
        return response

    def analyze_image_with_chatgpt(self, image_path):
        """ChatGPT API를 이용한 이미지 분석"""
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "이 이미지는 무엇이며, 중심점을 기준으로 해당 물체의 위치는? 질문 내용에만 대답" },
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
                        ]
                    }
                ],
                "max_tokens": 100
            }

            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

            if response.status_code == 200:
                result = response.json()
                analysis = result['choices'][0]['message']['content']
                self.get_logger().info(f'ChatGPT 분석 결과: {analysis}')
                return analysis
            else:
                self.get_logger().error(f'API 호출 실패: {response.status_code}, {response.text}')
                return None
        except Exception as e:
            self.get_logger().error(f'이미지 분석 중 오류 발생: {str(e)}')
            return None

def main():
    rclpy.init()
    node = ImageAnalyzerService()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()

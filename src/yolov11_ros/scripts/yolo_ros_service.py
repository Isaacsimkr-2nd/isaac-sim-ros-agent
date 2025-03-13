# when requested : subscribe /image and apply YOLOv11 model to the image

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_srvs.srv import Trigger
from cv_bridge import CvBridge
import cv2
import numpy as np
from ultralytics import YOLO

class YoloServer(Node):
    def __init__(self):
        super().__init__('yolo_server')
        # 이미지 구독 설정
        self.subscription = self.create_subscription(
            Image,
            '/camera_color_frame/image_raw',
            self.image_callback,
            10
        )
        # 서비스 설정
        self.srv = self.create_service(Trigger, 'run_yolo', self.run_yolo_callback)
        # YOLO 모델 초기화
        self.model_path = '/home/sang/yolo/yolo11n.pt'
        self.model = YOLO(self.model_path)
        # 최신 이미지 저장용 변수
        self.latest_image = None
        # CvBridge 초기화
        self.bridge = CvBridge()

    def image_callback(self, msg):
        """이미지 토픽에서 수신된 이미지를 최신 이미지로 저장"""
        self.latest_image = self.bridge.imgmsg_to_cv2(msg)

    def run_yolo_callback(self, request, response):
        """클라이언트 요청 시 저장된 최신 이미지로 YOLO 실행"""
        if self.latest_image is not None:
            # YOLO 실행
            results = self.model(self.latest_image)
            annotated_frame = results[0].plot()
            # 결과 화면 표시
            cv2.imshow("YOLOv8 Inference", annotated_frame)
            cv2.waitKey(1)
            # 응답 설정
            response.success = True
            response.message = "YOLO 실행 완료"
        else:
            response.success = False
            response.message = "사용 가능한 이미지가 없습니다"
        return response

def main():
    rclpy.init()
    yolo_server = YoloServer()
    rclpy.spin(yolo_server)
    yolo_server.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()
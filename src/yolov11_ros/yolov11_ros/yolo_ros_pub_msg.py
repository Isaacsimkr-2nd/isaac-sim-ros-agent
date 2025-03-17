import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from yolo_perception.msg import DetectionInfo, DetectionArray
from cv_bridge import CvBridge
import cv2
from ultralytics import YOLO

class YoloPerceptionNode(Node):
    def __init__(self):
        super().__init__('yolo_perception_node')
        
        # 이미지 토픽 (/rgb) 구독 설정
        self.subscription = self.create_subscription(
            Image,
            '/rgb',
            self.image_callback,
            10
        )
        
        # 감지 결과 토픽 (/detection_results) 발행 설정
        self.publisher = self.create_publisher(DetectionArray, '/detection_results', 10)
        
        # ROS Image와 OpenCV 이미지 변환을 위한 CvBridge 객체
        self.bridge = CvBridge()
        
        # YOLO 모델 초기화 (모델 경로는 사용자 환경에 맞게 수정 필요)
        self.model = YOLO('/home/sang/yolo/yolo11n.pt')
        self.model.conf = 0.7  # 신뢰도 임계값 설정 (0.0 ~ 1.0)

    def image_callback(self, msg):
        # ROS Image 메시지를 OpenCV 이미지로 변환
        cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        
        # YOLO 모델로 객체 감지 수행
        results = self.model(cv_image)
        
        # DetectionArray 메시지 객체 생성
        detection_array = DetectionArray()
        detection_array.count = len(results[0].boxes)  # 감지된 객체 수 설정
        
        # 각 감지된 객체를 DetectionInfo로 변환
        for box in results[0].boxes:
            detection_info = DetectionInfo()
            detection_info.label = self.model.names[int(box.cls)]  # 객체 레이블
            detection_info.confidence = float(box.conf)  # 신뢰도 (float32로 변환)
            detection_info.bounding_box = [int(coord) for coord in box.xyxy[0].tolist()]  # 바운딩 박스 좌표 [x_min, y_min, x_max, y_max]
            detection_info.width = int(box.xywh[0][2])  # 바운딩 박스 너비
            detection_info.height = int(box.xywh[0][3])  # 바운딩 박스 높이
            
            # DetectionArray에 추가
            detection_array.detections.append(detection_info)
        
        # 감지 결과 발행
        self.publisher.publish(detection_array)
        self.get_logger().info(f'Published {detection_array.count} detections')

def main(args=None):
    rclpy.init(args=args)
    node = YoloPerceptionNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
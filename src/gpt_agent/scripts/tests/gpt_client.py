import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger  # 요청할 서비스 타입

class ImageAnalyzerClient(Node):
    def __init__(self):
        super().__init__('image_analyzer_client')
        self.client = self.create_client(Trigger, 'analyze_image')

        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('서비스 연결 대기 중...')

        self.req = Trigger.Request()

    def send_request(self):
        """서비스 요청을 보냄"""
        future = self.client.call_async(self.req)
        rclpy.spin_until_future_complete(self, future)
        return future.result()

def main():
    rclpy.init()
    client = ImageAnalyzerClient()
    response = client.send_request()

    if response.success:
        print(f'이미지 분석 결과: {response.message}')
    else:
        print(f'요청 실패: {response.message}')

    rclpy.shutdown()

if __name__ == '__main__':
    main()

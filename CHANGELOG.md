# Change Log

### 2025-03-12
### 변경 사항

#### 이동 후 항상 위치 정보 확인
- `src/turtlebot3_agent/turtlebot3_agent/prompts`
    - constraints_and_guardrails
#### 위치정보 추가 및 위치정보 기반 제어로 수정
- `src/turtlebot3_agent/turtlebot3_agent/tools/turtlebot3.py`
    - odom_callback 추가 (현재 위치 정보 x,y,yaw)
    - forward_or_backward, rotate_in_place, move_with_direction에 odom 정보 추가

#### 기타
- `src/README.md`에서 로봇명 'turtlebot3' 수정

### 2025-03-13
### 변경 사항

#### YOLO for ROS2 추가
- `src/yolo_percepriton/` : custom msg 패키지
- `src/yolov11_ros/` : YOLO + ROS2 패키지
- `src/turtlebot3_agent/turtlebot3_agent/tools/turtlebot3.py`
    - Subscribe to /detection_results (DetectionArray)
    - Parse the detection info (label, confidence, bounding_box etc.)
    - Provide a yolo_tool() function

### 2025-03-15
### 변경 사항

#### ROS2 Executable (YOLO) 추가
- `ros2 run yolov11_ros yolov11_ros_viewer` : viewer
- `ros2 run yolov11_ros yolov11_msg_publisher` : detection msg publisher

#### turtlebot3.py, prompt.py 로직 수정
- turtlebot3.py : face_detection tool 추가
- prompt.py : deviance 관련 추가

### error
- 최초 실행 시 문제 발생
- 방향을 잡지 못하고 이동 (turtlebot3.find_detection)

### TO-DO
1. Service Client
2. launch 파일로 수정 후 argument로 img 변경 가능하게
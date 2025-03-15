from setuptools import find_packages, setup

package_name = 'yolov11_ros'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='sang',
    maintainer_email='lollolha97@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'yolov11_ros_viewer = yolov11_ros.yolo_ros_viewer:main',
            'yolov11_msg_publisher = yolov11_ros.yolo_ros_pub_msg:main',            
        ],
    },
)

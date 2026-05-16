"""grasp.launch.py — RealSense + grasp_node 동시 기동.

dsr_bringup2 는 별도 터미널에서 먼저 띄우는 것을 권장 (로봇 연결 안정성).
RealSense 와 grasp_node 만 한 번에 띄우는 것이 본 launch 의 역할.

사용 예:
    # dryrun (로봇 없이 변환 검증)
    ros2 launch gripper_approaching_sequence grasp.launch.py \\
        target_class:=smartphone dryrun:=true include_realsense:=true

    # 실로봇 + 그리퍼 (dsr_bringup2 가 별도 터미널에서 떠 있어야 함)
    ros2 launch gripper_approaching_sequence grasp.launch.py \\
        target_class:=glasses gripper_ip:=192.168.1.1
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    target_arg = DeclareLaunchArgument(
        "target_class", default_value="glasses",
        description="YOLO 클래스명 (plate/tissue/smartphone/remote/glasses/toy_block)")
    dryrun_arg = DeclareLaunchArgument(
        "dryrun", default_value="false",
        description="true 면 DSR/Gripper 호출 없음")
    rs_arg = DeclareLaunchArgument(
        "include_realsense", default_value="false",
        description="true 면 realsense2_camera launch 동시 실행")
    device_arg = DeclareLaunchArgument(
        "device", default_value="0", description="YOLO device: 0|cpu")
    vlm_model_arg = DeclareLaunchArgument(
        "vlm_model", default_value="gpt-4o", description="OpenAI vision model")
    gripper_type_arg = DeclareLaunchArgument(
        "gripper_type", default_value="rg2", description="rg2|rg6")
    gripper_ip_arg = DeclareLaunchArgument(
        "gripper_ip", default_value="",
        description="OnRobot Compute Box IP (빈 문자열이면 비활성)")
    gripper_port_arg = DeclareLaunchArgument(
        "gripper_port", default_value="502", description="Modbus TCP 포트")

    rs_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution([
            FindPackageShare("realsense2_camera"), "launch", "rs_align_depth_launch.py",
        ])),
        launch_arguments={
            "depth_module.depth_profile": "848x480x30",
            "rgb_camera.color_profile":   "1280x720x30",
            "initial_reset":              "true",
            "align_depth.enable":         "true",
            "enable_rgbd":                "true",
            "pointcloud.enable":          "true",
        }.items(),
        condition=IfCondition(LaunchConfiguration("include_realsense")),
    )

    grasp_node = Node(
        package="gripper_approaching_sequence",
        executable="grasp_node",
        name="grasp_perception_node",
        output="screen",
        arguments=[
            "--target",        LaunchConfiguration("target_class"),
            "--device",        LaunchConfiguration("device"),
            "--vlm-model",     LaunchConfiguration("vlm_model"),
            "--gripper-type",  LaunchConfiguration("gripper_type"),
            "--gripper-ip",    LaunchConfiguration("gripper_ip"),
            "--gripper-port",  LaunchConfiguration("gripper_port"),
        ],
        parameters=[{
            "target_class": LaunchConfiguration("target_class"),
        }],
    )

    return LaunchDescription([
        target_arg, dryrun_arg, rs_arg, device_arg, vlm_model_arg,
        gripper_type_arg, gripper_ip_arg, gripper_port_arg,
        rs_launch, grasp_node,
    ])

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import TimerAction

def generate_launch_description():
    # 1. 통합 파라미터 파일(params.yaml) 경로 가져오기
    bringup_dir = get_package_share_directory('cobot_bringup')
    params_file = os.path.join(bringup_dir, 'config', 'params.yaml')

    # 2. 실행할 노드들 정의
    
    # [로봇 제어 파트]
    executer_node = Node(
        package='cobot_core',
        executable='executer',  # setup.py의 entry_points에 등록된 이름
        name='executer',
        output='screen',
        parameters=[params_file]        # 🚨 yaml 파일 자동 주입
    )

    state_manager_node = Node(
        package='cobot_core',
        executable='state_manager',
        name='state_manager',
        output='screen',
        parameters=[params_file]
    )

    ui_bridge_node = Node(
        package='cobot_core',
        executable='ui_bridge',
        name='ui_bridge',
        output='screen',
        parameters=[params_file]
    )

    # [비전+파지 통합 파트] — grasp_perception_node
    # YOLO→VLM→포인트클라우드 구조 해석→그리퍼 자동대응. /grasp_object 서비스 제공.
    # grasp_node 는 argparse 기반 — 설정은 arguments= 로만 주입(ROS params 미사용).
    vision_node = Node(
        package='gripper_approaching_sequence',
        executable='grasp_node',
        name='grasp_perception_node',
        output='screen',
        arguments=['--gripper-ip', '192.168.1.1']
    )

    # [DB 릴레이] — ROS→MySQL. 디버깅 admin 컨테이너가 DDS 에 직접 참여
    # 못하는 문제 우회. 컨테이너는 ROS 없이 DB 만 read. DB 접속은 환경변수
    # (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD — debugging/.env 와 동일).
    db_logger_node = Node(
        package='cobot_core',
        executable='db_logger',
        name='db_logger',
        output='screen',
        parameters=[params_file]
    )

    # [음성 파트]
    # 음성 파이프라인은 sub1_side/web/backend 의 wakeup_worker 단독으로 일원화.
    # (wake→STT→LLM→/voice_command, TTS는 프론트 /tts) — 기존 voice_processing 노드 제거.

    bt_manager_node = Node(
        package='bt_manager',
        executable='bt_manager',  # CMakeLists.txt의 add_executable 이름
        name='bt_manager',
        output='screen',
        parameters=[params_file]  # 필요시 파라미터 공유
    )

    # 💡 꿀팁: 몸통·비전 노드가 켜질 시간을 벌어주기 위해 두뇌는 4초 뒤에 켭니다.
    delayed_bt_manager = TimerAction(
        period=4.0,
        actions=[bt_manager_node]
    )

    # 3. 위에서 정의한 모든 노드를 하나의 Launch Description으로 묶어서 반환
    return LaunchDescription([
        executer_node,
        state_manager_node,
        ui_bridge_node,
        vision_node,
        db_logger_node,
        delayed_bt_manager  # 일반 노드 대신 지연 실행 객체를 넣습니다.
    ])
#!/usr/bin/env bash
# start_session.sh — Semantic Grasp 실행을 위한 4-터미널 가이드
#
# 본 스크립트는 자동 실행이 아닌 "해야 할 명령"을 보여준다.
# 실제로는 각 단계를 별도 터미널에서 실행하라.
#
# 가정:
#   - cobot_ws 빌드 완료 (`colcon build --symlink-install`)
#   - ~/.bashrc 에 OPENAI_API_KEY export
#   - Doosan m0609 로봇이 192.168.1.100:12345 에서 동작 중
#   - OnRobot RG2/RG6 그리퍼가 IP <GRIPPER_IP> 로 연결됨
#   - RealSense D435/D455 가 USB 연결됨

set -e

cat <<'EOF'
═══════════════════════════════════════════════════════════════════
  Semantic Grasp 실행 절차 — 4 개 터미널 필요
═══════════════════════════════════════════════════════════════════

[Term 1] Doosan m0609 bring-up
  cd ~/cobot_ws
  source install/setup.bash
  ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
      mode:=real host:=192.168.1.100 port:=12345 model:=m0609

  (Tip) DSR 함수 path 가 안 잡히면:
  export PYTHONPATH=$PYTHONPATH:~/cobot_ws/install/dsr_common2/lib/dsr_common2/imp


[Term 2] RealSense
  source ~/cobot_ws/install/setup.bash
  ros2 launch realsense2_camera rs_align_depth_launch.py \
      depth_module.depth_profile:=848x480x30 \
      rgb_camera.color_profile:=1280x720x30 \
      initial_reset:=true \
      align_depth.enable:=true \
      enable_rgbd:=true \
      pointcloud.enable:=true


[Term 3-A] (선택) 직접교시 모드 + 좌표 추출 — Hand-Eye 캘리브레이션이나
            grasp 좌표 검증에 사용. cobot2/utils/rokey 의 도우미 노드.

  # 직접교시 (manual) 모드 진입:
  ros2 service call /dsr01/system/set_robot_mode \
      dsr_msgs2/srv/SetRobotMode "robot_mode: 0"

  # 좌표 표시 GUI:
  ros2 run rokey get_current_pos      # 또는 jog_complete 로 정밀 jog

[Term 3-B] (선택) jog 제어
  ros2 run rokey jog_complete


[Term 4] Semantic Grasp 메인 (서비스 모드)
  source ~/cobot_ws/install/setup.bash
  ros2 run gripper_approaching_sequence grasp_node \
      --target glasses \
      --gripper-ip 192.168.1.1 \
      --gripper-port 502 \
      --gripper-type rg2

  # 트리거:
  ros2 service call /semantic_grasp std_srvs/srv/Trigger {}


[Term 4-alt] GUI 디버그 모드 (퍼셉션만, 로봇 없이)
  python3 ~/cobot_ws/src/donttouch/gripper_approaching_sequence/gui_for_test/grasp_gui.py


  주의:
   - 그리퍼 사용 전 직접교시로 안전 위치에서 wide-open 동작 확인
   - 첫 실행은 항상 --dryrun 으로 좌표 검증
   - 'Term 1' 의 robot_mode 가 1 (auto/manual remote) 일 때만 movel 동작
═══════════════════════════════════════════════════════════════════
EOF

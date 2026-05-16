# Cross-host DDS 운영 노트 (sub1 ↔ main)

## 문제
`wakeup_worker`(sub1 = 서브 PC)가 발행하는 `/voice_command`·`/voice_reply`·`/stt_result`와
구독하는 `/ui_bridge/state`(상태 게이트), 그리고 main PC의 `bt_manager`/`db_logger`가
**서로 다른 PC**에 있다. ROS 2 DDS 디스커버리는 셸 환경(`ROS_DOMAIN_ID`,
`RMW_IMPLEMENTATION`)과 네트워크(멀티캐스트/유니캐스트)에 의존하는데, 이 설정이
repo 코드에 없다(있을 수도 없음 — 배포 환경 사안). 불일치 시 **토픽이 조용히
누락**되고, wakeup_worker 상태 게이트는 `/ui_bridge/state` 미수신 → 항상 IDLE 폴백
→ 로봇이 동작/정지 중인데도 음성 명령을 수용하는 위험이 있다.

## 양 PC 공통 환경 (둘 다 동일하게 source)

`~/.bashrc` 또는 워크스페이스 source 스크립트 끝에 추가, **sub1·main 동일**하게:

```bash
# 1) 같은 도메인 (debugging/.env 의 ROS_DOMAIN_ID 와 반드시 일치)
export ROS_DOMAIN_ID=0

# 2) 같은 RMW (한쪽만 cyclone, 한쪽 fastdds 면 통신 0)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 3) 멀티캐스트가 막힌 LAN 이면 유니캐스트 피어 명시 (CycloneDDS)
export CYCLONEDDS_URI=file:///etc/cyclonedds/cyclonedds.xml
```

`/etc/cyclonedds/cyclonedds.xml` (양 PC, IP는 실제 값으로):

```xml
<CycloneDDS><Domain>
  <Discovery>
    <ParticipantIndex>auto</ParticipantIndex>
    <Peers>
      <Peer address="192.168.0.10"/>   <!-- main PC -->
      <Peer address="192.168.0.20"/>   <!-- sub1 PC -->
    </Peers>
  </Discovery>
</Domain></CycloneDDS>
```

## 체크리스트
1. 두 PC `echo $ROS_DOMAIN_ID` 동일, `echo $RMW_IMPLEMENTATION` 동일.
2. `debugging/.env` 의 `ROS_DOMAIN_ID` 도 위와 동일(컨테이너는 db_logger 경유라
   직접 DDS 불필요하지만, 값 혼동 방지를 위해 일치 유지).
3. main 에서 `ros2 topic echo /voice_command` → sub1 에서 wake 발화 시 수신 확인.
4. sub1 에서 `ros2 topic echo /ui_bridge/state` → main `ui_bridge` 발행 수신 확인
   (미수신이면 상태 게이트가 IDLE 폴백 = 안전하지 않음).
5. 방화벽: DDS 기본 UDP 포트(7400±, 도메인별) 양방향 허용.

## 참고
- 컨테이너(`debugging/`)는 `db_logger`(main 호스트 네이티브)가 MySQL 에 적재 →
  컨테이너 자체는 DDS 그래프에 참여하지 않는다. 따라서 cross-host 문제는
  **sub1 ↔ main 호스트 노드 간**으로 한정된다.
- 이 문서는 코드 동작을 바꾸지 않는다(배포/운영 설정 가이드).

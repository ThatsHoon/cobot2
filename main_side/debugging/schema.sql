-- ============================================================
-- robot_admin — 단일 MySQL 구조 (v6, MongoDB 제거)
--
-- 이전(v5): MySQL 요약/인덱스 + MongoDB 계층 상세 (command_id/mongo_doc_id 링크)
-- 변경(v6): 단일 MySQL 로 통합.
--   - 계층 상세(parsed_text, full execution logs)는 command_logs.detail JSON 컬럼
--     (MySQL 8 네이티브 JSON). MongoDB·dual-write·고아 레코드 위험 제거.
--   - command_id 가 단일 PK. 요약+상세가 한 트랜잭션으로 원자적 기록.
--
-- 데이터 소스(통합 ROS 파이프라인):
--   raw_text       ← /stt_result
--   action_count   ← /voice_command (시퀀스 배열 길이)
--   status/current_action ← /status (bt_manager: {state,action,target})
--   detail         ← 파싱 시퀀스 + 액션별 실행 로그(계층 JSON)
--   error_logs     ← /rosout (level/node_name/message)
--
-- ⚠️ robot 컨테이너(사전빌드 이미지)가 이 스키마를 소비.
--    v6 적용 시 앱의 DB 접근 코드 변경 필요 — 파일 하단 [APP CONTRACT] 참조.
-- ⚠️ 이 스크립트는 docker-entrypoint-initdb.d 로 신규 볼륨 최초 1회만 실행.
--    기존 ./db_data/mysql 에는 별도 마이그레이션 필요 — 하단 [MIGRATION] 참조.
-- ============================================================

CREATE DATABASE IF NOT EXISTS robot_admin
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE robot_admin;

-- ── 명령 (요약 + 상세 일체) ──────────────────────────────────
-- 요약 컬럼은 집계·필터용. 계층 상세는 detail JSON 에 인라인.
-- (InnoDB 는 대형 JSON 을 off-page 저장 → detail 미참조 쿼리엔 I/O 영향 없음)
CREATE TABLE IF NOT EXISTS command_logs (
    command_id     VARCHAR(100) PRIMARY KEY,
    raw_text       TEXT,                       -- STT 원문 (/stt_result)
    status         VARCHAR(50),               -- bt_manager: IDLE/RUNNING/SUCCESS/FAILURE/PAUSED
                                               -- (앱에서 received/executing/done/failed 로 매핑.
                                               --  PAUSED=음성/관리자 비상정지)
    action_count   INT          DEFAULT 0,    -- 전체 액션 수 (/voice_command 길이)
    current_action VARCHAR(100),              -- 현재 실행 중인 액션명 (/status.action)
    error_count    INT          DEFAULT 0,    -- 비정규화 캐시 (정합 검증: COUNT(error_logs))
    detail         JSON,                       -- 계층 상세 (구 MongoDB command_documents)
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    started_at     DATETIME,                  -- 첫 EXECUTING 진입 시각
    finished_at    DATETIME,                  -- 완료·실패 시각
    INDEX idx_created_at (created_at),
    INDEX idx_status (status)                  -- 대시보드 상태 필터 (failed/executing)
);

-- ── 에러 로그 ────────────────────────────────────────────────
-- recommendations 규칙 매칭 + command 별 에러 집계.
CREATE TABLE IF NOT EXISTS error_logs (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    command_id VARCHAR(100),                  -- → command_logs.command_id (연결 키)
    level      VARCHAR(10),                  -- WARN / ERROR / FATAL (/rosout)
    node_name  VARCHAR(100),
    message    TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- (command_id, level) 복합이 좌측 프리픽스로 command_id 단독 조회/집계
    -- (연결 키·error_count 산출)까지 커버 → 별도 단일 인덱스 불필요
    INDEX idx_cmd_level (command_id, level),    -- 연결 키 조회 + recommendations 매칭
    INDEX idx_created_at (created_at)           -- "최근 에러" 시간범위 쿼리
);

-- ============================================================
-- [APP CONTRACT] robot-stack 이미지가 v6 에 맞춰 변경해야 할 사항
--   1. MongoDB 클라이언트/접속 제거 (pymongo 등). MONGO_* 환경변수 미사용.
--   2. 명령 기록: Mongo doc insert + mongo_doc_id 저장 → 폐기.
--      대신 command_logs INSERT/UPDATE 시 detail 컬럼에 계층 JSON 직접 기록
--      (요약+상세 단일 트랜잭션 → dual-write 정합 문제 소멸).
--   3. 상세 조회: mongo_doc_id 로 Mongo 조회 →
--      SELECT detail FROM command_logs WHERE command_id=%s 로 대체.
--   4. detail 내부 필드로 검색이 필요해지면, 그때 generated column +
--      함수 인덱스를 추가(스키마 확장). 현재는 command_id PK 조회 전제.
--
-- [MIGRATION] 기존 ./db_data/mysql 볼륨에 적용 시 (신규 init 아닌 경우)
--   -- 1) 컬럼 추가 (앱 배포 전, 무중단 안전)
--   ALTER TABLE command_logs ADD COLUMN detail JSON AFTER error_count;
--   ALTER TABLE command_logs ADD INDEX idx_status (status);
--   ALTER TABLE error_logs   ADD INDEX idx_cmd_level (command_id, level);
--   ALTER TABLE error_logs   ADD INDEX idx_created_at (created_at);
--   -- 2) (선택) 기존 Mongo command_documents → detail 백필 후
--   -- 3) 앱을 v6 코드로 교체하고 정상 동작 확인한 뒤 mongo_doc_id 제거
--   ALTER TABLE command_logs DROP COLUMN mongo_doc_id;
-- ============================================================

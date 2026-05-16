import importlib
import pkgutil
import time
import cobot_core.actions.logical_actions as logical_actions

from rclpy.callback_groups import MutuallyExclusiveCallbackGroup

from .base_action import BaseAction
from od_msg.srv import GraspObject
        
class ActionManager():
    def __init__(self, node):
        self.node = node
        self._action_map = {}
        self.is_error = False   # 시스템 에러 상태 플래그
        
        self.target = None
        self.target_pos = None
        
        self.cb_group = MutuallyExclusiveCallbackGroup()
        
        # 👁️ 통합 인지/파지 서비스 클라이언트 (grasp_perception_node)
        #   mode="locate" : base_pose 만 반환 (BT 변칙 대응 — 탐색/접근/tap)
        #   mode="grasp"  : 인지+접근+파지 실행 (동적 pick)
        # Hand-Eye 변환·자세 추정은 grasp_perception_node 가 전담한다.
        self.vision_client = self.node.create_client(GraspObject, '/grasp_object',
                                                     callback_group=self.cb_group)
        self._grasp_service_ready = False  # 최초 1회만 wait_for_service
        # /grasp_object 응답 최대 대기(초). VLM+모션 포함이라 넉넉히.
        self.grasp_call_timeout = 120.0

        # OnRobot 그리퍼 Modbus TCP 단일 연결
        try:
            from cobot_core.controller.onrobot import RG

            self.gripper = RG()
            self.node.get_logger().info("✅ OnRobot Modbus 연결 성공!")
        except Exception as e:
            self.node.get_logger().error("⚠️ 그리퍼 통신 연결 실패: {e}")
            self.gripper = None

        self._register_methods()
        self._register_custom_actions()
    
    
    def perform(self, action_name, **kwargs):
        if self.is_error:
            self.node.get_logger().info("에러 상황으로 perform 중단")
            return False
        
        action = self._action_map.get(action_name)
        if not action:
            self.node.get_logger().info(f"Error: {action_name}을 찾을 수 없습니다.")
            return False

        # callable(action.execute)를 통해 실행 가능 여부만 체크
        execute_func = getattr(action, 'execute', None)
        if callable(execute_func):
            # 파이썬 코드 에러 발생 시에도 안전망이 작동하도록 try-except
            try:
                result = execute_func(**kwargs)
            except Exception as e:
                self.node.get_logger().error(f"🐍 [PYTHON ERROR] {action_name} 파라미터 또는 문법 오류: {e}")
                self.handle_critical_error(action_name) # 에러 시에도 무조건 compliance_off 실행!
                return False
            
            # 동작 실패(False 반환) 감지 시 처리
            if result is False:
                self.handle_critical_error(action_name)
                return False
            
            return True
            
        return False
    
    def _register_methods(self):
        """BaseAction의 메서드 등록 (movel, movej, gripper_open 등)"""
        
        # 메서드 가져오기용 인스턴스 생성
        base = BaseAction(self)
        methods = ['movel', 'movej', 'wait', 'reset', 
                   'gripper_open', 'gripper_close', 'gripper_open_little',
                   'compliance_on', 'compliance_off', 'set_desired_force',
                   'periodic','amovej','amovel', 'movesx', 'movesj',
                   'get_current_posx','get_current_posj',
                   'clear_alarm', 'stop']
        
        for m in methods:
            # getattr(obj, name): 객체에서 속성 가져오기
            method = getattr(base, m)
            self._action_map[m] = type(f"Method_{m}", (object,), {"execute": staticmethod(method)})
            self.node.get_logger().info(f"Method Registered: {m}")
            
    def _register_custom_actions(self):
        """actions 폴더 내의 모든 액션들을 자동으로 등록"""
        # 파일 임포트
        for _, name, _ in pkgutil.iter_modules(logical_actions.__path__):
            full_module_name = f"cobot_core.actions.logical_actions.{name}"
            importlib.import_module(full_module_name)
        
        # 액션 등록
        for cls in BaseAction.__subclasses__():
            action_name = cls.action_name or cls.__name__.lower()
            
            # 동작 이름에 맞는 인스턴스를 등록
            self._action_map[action_name] = cls(self)
            self.node.get_logger().info(f"Action Registered: {action_name}")

    def _call_grasp(self, target_name, mode):
        """grasp_perception_node 의 /grasp_object 동기 호출. response 또는 None.

        finding 루프 등에서 _call_grasp 가 연속 호출되므로 가용성 확인은
        최초 1회만 (3초 타임아웃). 이후엔 즉시 호출 — 누적 대기 방지.
        """
        if not self._grasp_service_ready:
            if not self.vision_client.wait_for_service(timeout_sec=3.0):
                self.node.get_logger().error(
                    "👁️ ❌ grasp_perception_node(/grasp_object)가 응답하지 않습니다.")
                return None
            self._grasp_service_ready = True
        self.target = target_name
        req = GraspObject.Request()
        req.target_name = target_name
        req.mode = mode
        self.node.get_logger().info(f"👁️ 🔍 '{target_name}' /grasp_object 요청 (mode={mode})")
        # 동기 call() 은 grasp_node 가 행하면 액션 스레드를 무한 점유한다.
        # call_async + 타임아웃 폴링: future 는 별도 콜백그룹(분리된 MTExecutor
        # 스레드)에서 해소되므로 액션 스레드를 데드라인까지만 블록.
        try:
            future = self.vision_client.call_async(req)
        except Exception as e:
            self.node.get_logger().error(f"👁️ ❌ 서비스 호출 실패: {e}")
            return None
        deadline = time.time() + self.grasp_call_timeout
        while not future.done() and time.time() < deadline:
            time.sleep(0.05)
        if not future.done():
            self.node.get_logger().error(
                f"👁️ ❌ /grasp_object 타임아웃({self.grasp_call_timeout:.0f}s) "
                f"— '{target_name}' (mode={mode})")
            return None
        return future.result()

    def get_vision_target(self, target_name):
        """타겟 위치 확인(locate). Base 6-DOF [x,y,z,rx,ry,rz] 반환 또는 None.

        BT 변칙 대응(finding/search/detect_in_place/approach/tap)이 호출한다.
        Base 변환·자세 추정은 grasp_perception_node 가 수행한다.
        """
        resp = self._call_grasp(target_name, mode="locate")
        if resp is not None and resp.success:
            base_pos = [float(v) for v in resp.base_pose]
            self.node.get_logger().info(f"👁️ ✅ '{target_name}' base_pose: {base_pos}")
            self.target_pos = base_pos
            return base_pos
        err = resp.message if resp else "Service call failed"
        self.node.get_logger().error(f"👁️ ❌ '{target_name}' locate 실패: {err}")
        return None

    def request_grasp(self, target_name):
        """동적 pick. grasp_perception_node 가 인지→접근→파지까지 수행. bool 반환."""
        resp = self._call_grasp(target_name, mode="grasp")
        if resp is not None and resp.success:
            self.node.get_logger().info(
                f"🦾 ✅ '{target_name}' 파지 성공 (q={resp.quality:.2f}, "
                f"width={resp.width_mm:.1f}mm)")
            self.target_pos = None  # 1회성 — 다음 동작 위해 정리
            return True
        err = resp.message if resp else "Service call failed"
        self.node.get_logger().error(f"🦾 ❌ '{target_name}' 파지 실패: {err}")
        return False
    
    def reset_error(self):
        """is_error 래치 해제. 운영자 개입 후 신규 goal 수락 또는
        /admin_command UNLOCK 시 호출 — 노드 재시작 없이 복구."""
        if self.is_error:
            self.node.get_logger().info("♻️ is_error 해제 — 정상 동작 복귀")
        self.is_error = False

    def handle_critical_error(self, action_name):
        """어떤 동작이든 실패하면 즉시 로봇을 멈추고 예외 모드로 진입"""
        self.is_error = True
        
        # 재시도를 위해 로봇 상태(순응제어, 좌표계) 등 강제 초기화
        try:
            comp_off = self._action_map.get('compliance_off')
            if comp_off:
                comp_off.execute()
        except Exception as e:
            self.node.get_logger().error(f"상태 강제 초기화 중 무시된 오류: {e}")
            
        stop_action = self._action_map.get('stop')
        if stop_action:
            stop_action.execute()
            
        self.node.get_logger().error(f"🚨 [EMERGENCY] {action_name} 수행 중 실패! 시스템을 정지합니다.")
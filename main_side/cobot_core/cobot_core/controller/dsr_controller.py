# 최상단에 DSR_ROBOT2를 임포트하지 말 것

class DSRobotController:
    """dsr 라이브러리의 동작함수들을 매핑, 이곳의 함수들은 JSON 동작 시퀸스와 매칭되지 않습니다."""

    # [안전 한계치 하드코딩] 협동로봇의 일반적인 안전 제한 속도
    LIMIT_VEL_LINEAR = 500.0   # 최대 직선 속도 (mm/s)
    LIMIT_ACC_LINEAR = 500.0   # 최대 직선 가속도 (mm/s^2)
    LIMIT_VEL_ANGULAR = 180.0  # 최대 관절 속도 (deg/s)
    LIMIT_ACC_ANGULAR = 180.0  # 최대 관절 가속도 (deg/s^2)
    
    def __init__(self, manager):
        self.manager = manager  # ActionManager 참조
        
    @property
    def vel_linear(self):
        current_val = self.manager.node.vel_linear
        return min(current_val, self.LIMIT_VEL_LINEAR)

    @property
    def acc_linear(self):
        current_val = self.manager.node.acc_linear
        return min(current_val, self.LIMIT_ACC_LINEAR)

    @property
    def vel_angular(self):
        current_val = self.manager.node.vel_angular
        return min(current_val, self.LIMIT_VEL_ANGULAR)

    @property
    def acc_angular(self):
        current_val = self.manager.node.acc_angular
        return min(current_val, self.LIMIT_ACC_ANGULAR)
            
    # =================================================================
    # 로봇팔 기본 이동 함수
    # =================================================================
    def movel(self, pos, vel=None, acc=None, time=0, radius=0, mode='abs', ref='base'):
        v = vel if vel is not None else self.vel_linear
        a = acc if acc is not None else self.acc_linear
        
        from DSR_ROBOT2 import movel
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL, DR_BASE, DR_TOOL
        from DSR_ROBOT2 import posx
        
        if mode == 'abs':
            mode = DR_MV_MOD_ABS
        elif mode == 'rel':
            mode = DR_MV_MOD_REL
        else:
            print("❌ 잘못된 move 모드!")
        
        if ref == 'base':
            ref = DR_BASE
        elif ref == 'tool':
            ref = DR_TOOL
        else:
            print("❌ 잘못된 ref 모드!")
            return False
            
        pos = posx(pos)
        res = movel(pos, vel=v, acc=a, time=time, radius=radius, mod=mode, ref=ref)
        
        if res != 0:
            print(f"⚠️ 예외사항 발생!: {res}")
            return False
        
        return True

    def movej(self, joint, vel=None, acc=None, time=0, mode='rel'):
        v = vel if vel is not None else self.vel_angular
        a = acc if acc is not None else self.acc_angular
        
        from DSR_ROBOT2 import movej
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL
        from DSR_ROBOT2 import posj
        
        if mode == 'abs':
            mode = DR_MV_MOD_ABS
        elif mode == 'rel':
            mode = DR_MV_MOD_REL
        else:
            print("❌ 잘못된 move 모드!")
            
        joint = posj(joint)
        res = movej(joint, vel=v, acc=a, time=time, mod=mode)
        
        if res != 0:
            print(f"⚠️ 예외사항 발생!: {res}")
            return False
        
        return True

    def amovej(self, joint, vel=None, acc=None, time=0, mode='rel'):        
        v = vel if vel is not None else self.vel_angular        
        a = acc if acc is not None else self.acc_angular
        
        from DSR_ROBOT2 import amovej        
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL        
        from DSR_ROBOT2 import posj
        
        if mode == 'abs':            
            mode = DR_MV_MOD_ABS        
        elif mode == 'rel':            
            mode = DR_MV_MOD_REL        
        else:            
            print("❌ 잘못된 move 모드!")            
            return False
        
        joint = posj(joint)
        
        res = amovej(
                    joint,
                    vel=v,
                    acc=a,
                    time=time,
                    mod=mode,
                    )
                    
        if res != 0:            
            print(f"⚠️ amovej 예외사항 발생!: {res}")            
            return False
        return True

    def amovel(self, pos, vel=None, acc=None, time=0, mode='abs', ref='base'):
        v = vel if vel is not None else self.vel_linear
        a = acc if acc is not None else self.acc_linear

        from DSR_ROBOT2 import amovel
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL, DR_BASE, DR_TOOL
        from DSR_ROBOT2 import posx

        if mode == 'abs':
            mode = DR_MV_MOD_ABS
        elif mode == 'rel':
            mode = DR_MV_MOD_REL
        else:
            print("❌ 잘못된 move 모드!")
            return False

        pos = posx(pos)

        res = amovel(
            pos,
            vel=v,
            acc=a,
            time=time,
            mod=mode,
        )

        if res != 0:
            print(f"⚠️ amovel 예외사항 발생!: {res}")
            return False

        return True

    def movesj(self, joints, vel=None, acc=None, time=0, mode='abs'):
        v = vel if vel is not None else self.vel_angular        
        a = acc if acc is not None else self.acc_angular
        
        from DSR_ROBOT2 import movesj        
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL        
        from DSR_ROBOT2 import posj

        if mode == 'abs':            
            mode = DR_MV_MOD_ABS        
        elif mode == 'rel':            
            mode = DR_MV_MOD_REL        
        else:            
            print("❌ 잘못된 move 모드!")            
            return False
            
        path = [posj(joint) for joint in joints]
        res = movesj(            
                    path,            
                    vel=v,            
                    acc=a,            
                    time=time,            
                    mod=mode,        
                    )
        if res != 0:            
            print(f"⚠️ movesj 예외사항 발생!: {res}")            
            return False
            
        return True

    def movesx(self, poses, vel=None, acc=None, time=0, 
								 mode='abs', ref='base'):        
        v = vel if vel is not None else self.vel_linear        
        a = acc if acc is not None else self.acc_linear
            
        from DSR_ROBOT2 import movesx        
        from DSR_ROBOT2 import DR_MV_MOD_ABS, DR_MV_MOD_REL, DR_BASE, DR_TOOL        
        from DSR_ROBOT2 import posx
        
        if mode == 'abs':
            mode = DR_MV_MOD_ABS
        elif mode == 'rel':
            mode = DR_MV_MOD_REL
        else:
            print("❌ 잘못된 move 모드!")
            return False
        
        if ref == 'base':
            ref = DR_BASE
        elif ref == 'tool':
            ref = DR_TOOL
        else:
            print("❌ 잘못된 ref 모드!")
            return False
        
        path = [posx(pos) for pos in poses]
        
        res = movesx(
                    path,
                    vel=v,
                    acc=a,
                    time=time,
                    mod=mode,
                    ref=ref,
                    )
                            
        if res != 0:
            print(f"⚠️ movesx 예외사항 발생!: {res}")
            return False

        return True
    
    def periodic(self, amp, period, repeat):
        from DSR_ROBOT2 import move_periodic, DR_BASE

        res = move_periodic(amp=amp, period=period, repeat=repeat, ref=DR_BASE)
        
        if res != 0:
            print(f"⚠️ 예외사항 발생!: {res}")
            return False
        
        return True
    
    # =================================================================
    # OnRobot Modbus를 통한 Gripper 제어 함수
    # RG2 기준 단위: force(1/10 N, 0~400), width(1/10 mm, 0~1100)
    # =================================================================
    def gripper_open(self, force=400):
        """그리퍼를 최대 폭으로 개방합니다."""
        if hasattr(self.manager, 'gripper') and self.manager.gripper:
            self.manager.gripper.open_gripper(force_val=force)
            self.wait(1.0) # 동작 안정화 대기
        else:
            print("⚠️ 그리퍼가 연결되어 있지 않습니다.")
            
    def gripper_close(self, force=400):
        """그리퍼를 완전히 닫아 파지합니다."""
        if hasattr(self.manager, 'gripper') and self.manager.gripper:
            self.manager.gripper.close_gripper(force_val=force)
            self.wait(1.0)
            
            # (선택) onrobot.py의 get_status()를 활용해 제대로 잡혔는지 확인 가능
            # status = self.manager.gripper.get_status()
            # if status[1] == 1: print("✨ 물체 파지 성공!")
        else:
            print("⚠️ 그리퍼가 연결되어 있지 않습니다.")

    def gripper_open_little(self, width=650, force=400):
        """그리퍼를 RG2 최대 폭의 절반(55mm)보다 1cm만큼 더 정밀하게 엽니다."""
        if hasattr(self.manager, 'gripper') and self.manager.gripper:
            # move_gripper는 특정 폭(width_val)으로 이동합니다.
            self.manager.gripper.move_gripper(width_val=width, force_val=force)
            self.wait(1.0)
        else:
            print("⚠️ 그리퍼가 연결되어 있지 않습니다.")
    
    def gripper_close_little(self, width=450, force=400):
        """그리퍼를 RG2 최대 폭의 절반(55mm)보다 1cm만큼 덜 정밀하게 닫습니다."""
        if hasattr(self.manager, 'gripper') and self.manager.gripper:
            # move_gripper는 특정 폭(width_val)으로 이동합니다.
            self.manager.gripper.move_gripper(width_val=width, force_val=force)
            self.wait(1.0)
        else:
            print("⚠️ 그리퍼가 연결되어 있지 않습니다.")

    # =================================================================
    # 힘제어 함수
    # =================================================================
    def compliance_on(self, stx=[500, 500, 500, 100, 100, 100], ref='tool'):
        """
        순응 제어(Compliance Control)를 시작합니다.
        :param stx: 각 축(x, y, z, rx, ry, rz)에 대한 강성(Stiffness) 값의 리스트.
                    값이 작을수록 부드럽게(스프링처럼) 움직입니다.
        """
        from DSR_ROBOT2 import task_compliance_ctrl, set_ref_coord
        from DSR_ROBOT2 import DR_BASE, DR_TOOL
        
        # 순응 제어 활성화 '전'에만 기준 좌표계를 설정해야함
        ref_val = DR_TOOL if ref == 'tool' else DR_BASE
        set_ref_coord(ref_val)
            
        res = task_compliance_ctrl(stx=stx)
            
        self.wait(1)
        
        if res != 0:
            print(f"⚠️ 컴플라이언스 제어 활성화 실패: {res}")
            return False
            
        return True
    
    def compliance_off(self):
        """순응 제어를 해제하고 원래의 강성(Rigid) 제어 상태로 복귀합니다."""
        from DSR_ROBOT2 import release_compliance_ctrl, set_ref_coord, DR_BASE
        
        res = release_compliance_ctrl()
        set_ref_coord(DR_BASE)
        
        if res != 0:
            print(f"⚠️ 컴플라이언스 제어 해제 실패: {res}")
            return False
        
        return True
    
    def set_desired_force(self, fd=[0, 0, 0, 0, 0, 0], dir=[0, 0, 0, 0, 0, 0], ref='tool', mode='rel'):
        """
        로봇이 특정 방향으로 가할 목표 힘을 설정합니다.
        :param fd: 목표 힘/토크 리스트 (N 또는 Nm)
        :param dir: 힘을 가할 방향 (1: 활성화, 0: 비활성화)
        :param mode: 힘 제어 모드 ('abs' 또는 'rel')
        """
        from DSR_ROBOT2 import set_desired_force
        from DSR_ROBOT2 import DR_FC_MOD_ABS, DR_FC_MOD_REL
        
        fc_mode = DR_FC_MOD_ABS if mode == 'abs' else DR_FC_MOD_REL
        
        # DSR 파이썬 API에 ref 키워드가 없으므로 함수 호출 시 넘기지 않습니다.
        # (compliance_on에서 설정된 ref를 시스템이 자동으로 따라갑니다)
        res = set_desired_force(fd=fd, dir=dir, mod=fc_mode)
        
        if res != 0:
            print(f"⚠️ 목표 힘 설정 실패: {res}")
            return False
            
        return True
    
    # =================================================================
    # 그 외 제공 함수들
    # =================================================================
    def stop(self):
        try:
            # 구버전 API의 정지 함수인 task_stop을 마지막으로 시도해봅니다.
            from DSR_ROBOT2 import task_stop, STOP_TYPE_QUICK
            task_stop(STOP_TYPE_QUICK)
            print("🚨 [긴급] 로봇 모션을 강제 정지했습니다!")
        except ImportError:
            # 어떤 이름의 stop 함수도 없다면, 그냥 무시하고 넘어가서 파이썬 에러를 방지합니다.
            print("🚨 [긴급] 로봇 정지 명령 호출됨 (현재 API에서 지원하지 않아 로그만 출력합니다)")
            pass
        
    def wait(self, time=0):
        """wait(0)을 자주 쓰므로 편의를 위해 래핑"""
        from DSR_ROBOT2 import wait
        return wait(time)

    def get_current_posx(self):
        from DSR_ROBOT2 import get_current_posx

        pos, _ = get_current_posx()
        print(pos)
        return pos

    def get_current_posj(self):
        from DSR_ROBOT2 import get_current_posj

        raw = get_current_posj()

        # DSR 반환형이 (joint, sol) 형태인 경우
        if isinstance(raw, tuple):
            joint = raw[0]

        # DSR 반환형이 [joint, sol] 형태인 경우
        elif isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], (list, tuple)):
            joint = raw[0]

        # DSR 반환형이 [j1, j2, j3, j4, j5, j6] 형태인 경우
        else:
            joint = raw

        joint = list(joint[:6])
        print(joint)
        return joint

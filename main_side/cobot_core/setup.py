# cobot_core/setup.py

import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'cobot_core'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # resource 폴더 내의 모든 파일(.npy 등)을 빌드 후 share 경로로 복사
        (os.path.join('share', package_name, 'resource'), glob('resource/*')),
    ],
    install_requires=['setuptools', 'pymysql'],
    zip_safe=True,
    maintainer='kibeom',
    maintainer_email='neopkrrl@gmail.com',
    description='Core control package for Cobot2 (State, Executer, Skill Orchestrator)',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'state_manager = cobot_core.state_manager:main',
            'executer = cobot_core.controller.executer:main',
            'ui_bridge = cobot_core.ui_bridge:main',
            'db_logger = cobot_core.db_logger:main',
            'test_action = cobot_core.test_action:main'
        ],
    },
)
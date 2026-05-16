import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'gripper_approaching_sequence'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'scripts'), glob('scripts/*.sh')),
        # Hand-Eye 캘리브레이션 행렬(T_gripper2camera.npy) 등 리소스
        (os.path.join('share', package_name, 'resource'), glob('resource/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='Semantic Grasping (YOLO + VLM + RGB-D + PCA) for Doosan m0609',
    license='TODO',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'grasp_node = gripper_approaching_sequence.grasp_node:main',
            'grasp_dryrun = gripper_approaching_sequence.grasp_node:dryrun_main',
        ],
    },
)

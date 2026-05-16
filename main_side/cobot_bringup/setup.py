import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'cobot_bringup'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # config 폴더 등록
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        # 나중을 위해 launch 폴더도 미리 등록
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='kibeom',
    maintainer_email='neopkrrl@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
        ],
    },
)

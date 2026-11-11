from setuptools import find_packages, setup

package_name = 'cine_interfaces'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['contract.json']},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='fishnos',
    maintainer_email='fishnos@users.noreply.github.com',
    description=(
        'The contract for every ROS 2 topic that crosses Wi-Fi between CINE-Sensing and '
        'CINE, with static and live checks against it.'
    ),
    license='GPL-3.0-only',
    extras_require={'test': ['pytest']},
)

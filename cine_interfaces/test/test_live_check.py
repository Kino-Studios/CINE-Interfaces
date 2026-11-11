import shutil
import subprocess
import time
from pathlib import Path

import pytest
from cine_interfaces.contract import parse
from cine_interfaces.live_check import (
    GraphEndpoint,
    check_live,
    parse_topic_info,
    ros2_topic_info,
)

FIXTURE_TEXT = (Path(__file__).parent / 'fixtures' / 'topic_info_odometry.txt').read_text()


def _contract(accepted_mismatch=False, message_type='nav_msgs/msg/Odometry'):
    return parse(
        {
            'contract_version': 1,
            'streams': [
                {
                    'key': 'position_estimate',
                    'description': 'VIO odometry',
                    'message_type': message_type,
                    'direction': 'pi_to_ground',
                    'accepted_mismatch': accepted_mismatch,
                    'publishers': [
                        {
                            'repository': 'CINE-Sensing',
                            'node': 'vio_publisher',
                            'topic': '/vio/odometry',
                            'source': {'kind': 'code', 'file': 'vio_publisher.py'},
                        },
                    ],
                    'subscribers': [
                        {
                            'repository': 'CINE',
                            'node': 'ego_planner_node',
                            'topic': '/vio/odometry',
                            'source': {'kind': 'unchecked', 'reason': 'C++'},
                        },
                        {
                            'repository': 'external',
                            'node': 'mavros',
                            'topic': '/mavros/odometry/out',
                            'source': {'kind': 'unchecked', 'reason': 'MAVROS'},
                        },
                    ],
                },
            ],
        },
    )


def _errors(findings):
    return [finding for finding in findings if finding.severity == 'error']


def test_parse_topic_info_reads_publisher_and_subscription():
    endpoints = parse_topic_info(FIXTURE_TEXT)

    assert endpoints == [
        GraphEndpoint('vio_publisher', '/', 'nav_msgs/msg/Odometry', 'PUBLISHER'),
        GraphEndpoint('ego_planner_node', '/drone_0', 'nav_msgs/msg/Odometry', 'SUBSCRIPTION'),
    ]


def test_stream_with_publisher_and_subscriber_passes():
    findings = check_live(_contract(), topic_info=lambda topic: FIXTURE_TEXT)

    assert _errors(findings) == []


def test_unknown_topic_is_an_error():
    errors = _errors(check_live(_contract(), topic_info=lambda topic: None))

    assert len(errors) == 2
    assert '/vio/odometry' in errors[0].message


def test_missing_subscription_is_an_error():
    publisher_only = FIXTURE_TEXT.split('Subscription count')[0]

    errors = _errors(check_live(_contract(), topic_info=lambda topic: publisher_only))

    assert len(errors) == 1
    assert 'ego_planner_node' in errors[0].message


def test_wrong_topic_type_is_an_error():
    contract = _contract(message_type='geometry_msgs/msg/PoseStamped')

    errors = _errors(check_live(contract, topic_info=lambda topic: FIXTURE_TEXT))

    assert len(errors) == 2


def test_accepted_mismatch_failure_is_info_when_not_strict():
    findings = check_live(_contract(accepted_mismatch=True), topic_info=lambda topic: None)

    assert _errors(findings) == []
    assert len(findings) == 2


def test_accepted_mismatch_failure_is_error_when_strict():
    findings = check_live(
        _contract(accepted_mismatch=True),
        topic_info=lambda topic: None,
        strict=True,
    )

    assert len(_errors(findings)) == 2


def test_external_endpoints_are_not_queried():
    queried = []

    def recording_topic_info(topic):
        queried.append(topic)

        return FIXTURE_TEXT

    check_live(_contract(), topic_info=recording_topic_info)

    assert queried == ['/vio/odometry']


@pytest.mark.skipif(shutil.which('ros2') is None, reason='needs a ROS 2 installation')
def test_live_graph_publisher_is_found():
    topic = '/cine_interfaces_probe'
    publisher = subprocess.Popen(
        ['ros2', 'topic', 'pub', '--rate', '5', topic, 'std_msgs/msg/String', '{data: probe}'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        deadline = time.monotonic() + 20.0
        endpoints = []

        while time.monotonic() < deadline:
            text = ros2_topic_info(topic)
            endpoints = parse_topic_info(text) if text else []
            if any(endpoint.endpoint_type == 'PUBLISHER' for endpoint in endpoints):
                break
    finally:
        publisher.terminate()
        publisher.wait(timeout=10)

    assert [
        endpoint.topic_type for endpoint in endpoints if endpoint.endpoint_type == 'PUBLISHER'
    ] == ['std_msgs/msg/String']


def _graph_text(*blocks):
    return '\n'.join(
        f'Node name: {node}\nNode namespace: /\nTopic type: nav_msgs/msg/Odometry\n'
        f'Endpoint type: {endpoint_type}\n'
        for node, endpoint_type in blocks
    )


def _split_topic_contract(accepted_mismatch=False):
    return parse(
        {
            'contract_version': 1,
            'streams': [
                {
                    'key': 'position_estimate',
                    'description': 'VIO odometry',
                    'message_type': 'nav_msgs/msg/Odometry',
                    'direction': 'pi_to_ground',
                    'accepted_mismatch': accepted_mismatch,
                    'publishers': [
                        {
                            'repository': 'CINE-Sensing',
                            'node': 'vio_publisher',
                            'topic': '/vio/odometry',
                            'source': {'kind': 'code', 'file': 'vio_publisher.py'},
                        },
                    ],
                    'subscribers': [
                        {
                            'repository': 'CINE',
                            'node': 'light_vector_analysis',
                            'topic': '/odom_world',
                            'source': {'kind': 'unchecked', 'reason': 'test'},
                        },
                    ],
                },
            ],
        },
    )


SPLIT_GRAPH = {
    '/vio/odometry': _graph_text(('vio_publisher', 'PUBLISHER')),
    '/odom_world': _graph_text(('light_vector_analysis', 'SUBSCRIPTION')),
}


def test_subscriber_on_a_topic_nobody_publishes_is_an_error():
    errors = _errors(check_live(_split_topic_contract(), topic_info=SPLIT_GRAPH.get))

    assert len(errors) == 1
    assert 'light_vector_analysis' in errors[0].message
    assert 'no PUBLISHER' in errors[0].message


def test_unpublished_subscriber_of_accepted_stream_is_an_error_when_strict():
    findings = check_live(
        _split_topic_contract(accepted_mismatch=True),
        topic_info=SPLIT_GRAPH.get,
        strict=True,
    )

    assert len(_errors(findings)) == 1


def test_unpublished_subscriber_of_accepted_stream_is_info_when_not_strict():
    findings = check_live(_split_topic_contract(accepted_mismatch=True), topic_info=SPLIT_GRAPH.get)

    assert _errors(findings) == []
    assert len(findings) == 1

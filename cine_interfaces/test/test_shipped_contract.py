from cine_interfaces.contract import load


def _stream(key):
    return load().stream(key)


def test_shipped_contract_has_every_designed_stream():
    keys = {stream.key for stream in load().streams}

    assert keys == {
        'camera_image',
        'camera_info',
        'subject_center',
        'subject_box',
        'subject_size',
        'position_estimate',
        'position_estimate_imu_rate',
        'position_pose',
        'depth_image',
        'setpoint_translational_position',
        'setpoint_translational_velocity',
        'setpoint_translational_acceleration',
        'setpoint_attitude_position',
        'setpoint_attitude_velocity',
        'mavros_raw_setpoint',
        'simulated_position_estimate',
    }


def test_shipped_contract_records_hardware_odometry():
    stream = load().stream('position_estimate_imu_rate')

    assert stream.subscribers[0].topic == '/imu_propagate'


def test_planner_adapter_publishes_translational_position_setpoints():
    stream = _stream('setpoint_translational_position')
    publishers = [(p.repository, p.node, p.topic) for p in stream.publishers]

    assert publishers == [
        ('CINE', 'planner_setpoint_adapter', '/cinematography/translational_position_setpoints'),
    ]


def test_ground_side_reads_vio_odometry():
    stream = _stream('position_estimate')

    assert {s.topic for s in stream.subscribers} == {'/vio/odometry'}


def test_only_designed_streams_accept_a_mismatch():
    accepted = {stream.key for stream in load().streams if stream.accepted_mismatch}

    assert accepted == {
        'camera_info',
        'setpoint_translational_velocity',
        'setpoint_translational_acceleration',
        'setpoint_attitude_position',
        'setpoint_attitude_velocity',
    }


def test_every_accepted_mismatch_is_actually_mismatched():
    stale = [
        stream.key
        for stream in load().streams
        if stream.accepted_mismatch and not stream.is_mismatched
    ]

    assert stale == []


def test_simulator_flight_controller_odometry_is_checked_only_in_sim():
    stream = _stream('simulated_position_estimate')

    assert stream.modes == ('sim',)
    assert stream.topic_names == {'/mavros/local_position/odom'}


def test_vio_odometry_is_checked_only_on_the_drone():
    assert _stream('position_estimate').modes == ('hardware',)


def test_streams_of_the_orbit_node_are_checked_only_on_the_drone():
    for key in ('camera_info', 'position_pose', 'mavros_raw_setpoint'):
        assert _stream(key).modes == ('hardware',), key


def test_detection_streams_are_checked_in_both_modes():
    for key in ('camera_image', 'subject_center', 'depth_image'):
        assert _stream(key).modes == ('hardware', 'sim'), key

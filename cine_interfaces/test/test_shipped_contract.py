from cine_interfaces.contract import load

SETPOINT_STREAM_KEYS = {
    'setpoint_translational_position',
    'setpoint_translational_velocity',
    'setpoint_translational_acceleration',
    'setpoint_attitude_position',
    'setpoint_attitude_velocity',
}


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
    }


def test_shipped_contract_records_hardware_odometry():
    stream = load().stream('position_estimate_imu_rate')

    assert stream.subscribers[0].topic == '/imu_propagate'


def test_only_designed_streams_accept_a_mismatch():
    accepted = {stream.key for stream in load().streams if stream.accepted_mismatch}

    assert accepted == {'camera_image', 'camera_info', 'position_estimate', 'depth_image'} | (
        SETPOINT_STREAM_KEYS
    )


def test_every_accepted_mismatch_is_actually_mismatched():
    stale = [
        stream.key
        for stream in load().streams
        if stream.accepted_mismatch and not stream.is_mismatched
    ]

    assert stale == []

import pytest
from cine_interfaces.contract import Contract, ContractError, load, parse


def _pose_document():
    return {
        'contract_version': 1,
        'streams': [
            {
                'key': 'position_pose',
                'description': 'VIO pose for the orbit node',
                'message_type': 'geometry_msgs/msg/PoseStamped',
                'direction': 'pi_to_ground',
                'accepted_mismatch': False,
                'publishers': [
                    {
                        'repository': 'CINE-Sensing',
                        'node': 'vio_publisher',
                        'topic': '/vio/pose',
                        'source': {
                            'kind': 'code',
                            'file': 'cine_sensing_imu/cine_sensing_imu/vio_publisher.py',
                        },
                    },
                ],
                'subscribers': [
                    {
                        'repository': 'CINE',
                        'node': 'orbit_waypoint_generator',
                        'topic': '/vio/pose',
                        'source': {'kind': 'code', 'file': 'cine_agent/orbit.py'},
                    },
                ],
            },
        ],
    }


def test_valid_document_parses_into_streams():
    contract = parse(_pose_document())

    assert contract.stream('position_pose').publishers[0].topic == '/vio/pose'


def test_unknown_stream_field_is_rejected_with_its_name():
    document = _pose_document()
    document['streams'][0]['subscriber'] = []

    with pytest.raises(ContractError, match=r'position_pose.*subscriber'):
        parse(document)


def test_missing_field_is_rejected():
    document = _pose_document()
    del document['streams'][0]['message_type']

    with pytest.raises(ContractError, match='message_type'):
        parse(document)


def test_relative_topic_is_rejected():
    document = _pose_document()
    document['streams'][0]['publishers'][0]['topic'] = 'vio/pose'

    with pytest.raises(ContractError, match='vio/pose'):
        parse(document)


def test_trailing_slash_topic_is_rejected():
    document = _pose_document()
    document['streams'][0]['publishers'][0]['topic'] = '/vio/pose/'

    with pytest.raises(ContractError, match='/vio/pose/'):
        parse(document)


def test_malformed_message_type_is_rejected():
    document = _pose_document()
    document['streams'][0]['message_type'] = 'PoseStamped'

    with pytest.raises(ContractError, match='PoseStamped'):
        parse(document)


def test_duplicate_stream_key_is_rejected():
    document = _pose_document()
    document['streams'].append(_pose_document()['streams'][0])

    with pytest.raises(ContractError, match='duplicate'):
        parse(document)


def test_unsupported_contract_version_is_rejected():
    document = _pose_document()
    document['contract_version'] = 2

    with pytest.raises(ContractError, match='contract_version'):
        parse(document)


def test_external_endpoint_must_be_unchecked():
    document = _pose_document()
    document['streams'][0]['subscribers'][0]['repository'] = 'external'

    with pytest.raises(ContractError, match='external'):
        parse(document)


def test_config_source_requires_key():
    document = _pose_document()
    document['streams'][0]['publishers'][0]['source'] = {
        'kind': 'config',
        'file': 'config/topics.json',
    }

    with pytest.raises(ContractError, match='key'):
        parse(document)


def test_stream_with_two_topic_names_is_mismatched():
    document = _pose_document()
    document['streams'][0]['subscribers'][0]['topic'] = '/odom_world'

    assert parse(document).stream('position_pose').is_mismatched


def test_stream_with_one_topic_name_is_not_mismatched():
    assert not parse(_pose_document()).stream('position_pose').is_mismatched


def test_stream_without_publishers_is_mismatched():
    document = _pose_document()
    document['streams'][0]['publishers'] = []

    assert parse(document).stream('position_pose').is_mismatched


def test_endpoints_in_returns_only_that_repository():
    endpoints = parse(_pose_document()).endpoints_in('CINE-Sensing')

    assert len(endpoints) == 1
    assert endpoints[0][2] == 'publisher'


def test_packaged_contract_loads():
    contract = load()

    assert isinstance(contract, Contract)
    assert contract.version == 1

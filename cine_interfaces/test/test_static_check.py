import json

from cine_interfaces.contract import parse
from cine_interfaces.static_check import check_repository


def _contract(publisher_source, publisher_topic='/vio/odometry', **stream_overrides):
    stream = {
        'key': 'position_estimate',
        'description': 'VIO odometry',
        'message_type': 'nav_msgs/msg/Odometry',
        'direction': 'pi_to_ground',
        'accepted_mismatch': False,
        'publishers': [
            {
                'repository': 'CINE-Sensing',
                'node': 'vio_publisher',
                'topic': publisher_topic,
                'source': publisher_source,
            },
        ],
        'subscribers': [
            {
                'repository': 'CINE',
                'node': 'planner',
                'topic': '/vio/odometry',
                'source': {'kind': 'unchecked', 'reason': 'C++ in third_party'},
            },
        ],
    }
    stream.update(stream_overrides)

    return parse({'contract_version': 1, 'streams': [stream]})


def _code_source(file='vio_publisher.py'):
    return {'kind': 'code', 'file': file}


def _write(root, relative_path, text):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _errors(findings):
    return [finding for finding in findings if finding.severity == 'error']


def _infos(findings):
    return [finding for finding in findings if finding.severity == 'info']


def test_matching_publisher_literal_passes(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []


def test_qualified_message_type_name_passes(tmp_path):
    _write(
        tmp_path,
        'vio_publisher.py',
        "self.create_publisher(nav_msgs.msg.Odometry, '/vio/odometry', 10)\n",
    )

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []


def test_renamed_topic_literal_is_an_error(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odom', 10)\n")

    errors = _errors(check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'vio_publisher.py'


def test_wrong_message_type_is_an_error(tmp_path):
    _write(
        tmp_path,
        'vio_publisher.py',
        "self.create_publisher(PoseStamped, '/vio/odometry', 10)\n",
    )

    errors = _errors(check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert 'Odometry' in errors[0].message


def test_publisher_listed_as_subscriber_is_an_error(tmp_path):
    _write(
        tmp_path,
        'vio_publisher.py',
        "self.create_subscription(Odometry, '/vio/odometry', callback, 10)\n",
    )

    errors = _errors(check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert 'create_publisher' in errors[0].message


def test_missing_source_file_is_an_error_finding(tmp_path):
    errors = _errors(check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'vio_publisher.py'
    assert 'not found' in errors[0].message


def test_config_key_matching_topic_passes(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {'odom_topic': '/vio/odometry'}}))
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    findings = check_repository(_contract(source), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []


def test_config_key_with_other_topic_is_an_error(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {'odom_topic': '/odom_world'}}))
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert '/odom_world' in errors[0].message


def test_config_key_absent_is_an_error(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {}}))
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1


def test_profile_overriding_config_topic_is_an_error(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {'odom_topic': '/vio/odometry'}}))
    _write(
        tmp_path,
        'config/profiles/tune/vio.json',
        json.dumps({'vio': {'odom_topic': '/odometry'}}),
    )
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'config/profiles/tune/vio.json'


def test_profile_without_the_key_is_ignored(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {'odom_topic': '/vio/odometry'}}))
    _write(tmp_path, 'config/profiles/tune/vio.json', json.dumps({'other': 1}))
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    findings = check_repository(_contract(source), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []


def test_launch_parameter_matching_topic_passes(tmp_path):
    _write(
        tmp_path,
        'launch/run.launch.py',
        "Node(executable='vio_publisher', parameters=[{'odom_topic': '/vio/odometry'}])\n",
    )
    source = {
        'kind': 'launch',
        'file': 'launch/run.launch.py',
        'executable': 'vio_publisher',
        'parameter': 'odom_topic',
    }

    findings = check_repository(_contract(source), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []


def test_launch_parameter_changed_is_an_error(tmp_path):
    _write(
        tmp_path,
        'launch/run.launch.py',
        "Node(executable='vio_publisher', parameters=[{'odom_topic': '/odom'}])\n",
    )
    source = {
        'kind': 'launch',
        'file': 'launch/run.launch.py',
        'executable': 'vio_publisher',
        'parameter': 'odom_topic',
    }

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'launch/run.launch.py'


def test_unchecked_endpoint_is_info_only(tmp_path):
    findings = check_repository(_contract(_code_source()), 'CINE', tmp_path)

    assert _errors(findings) == []
    assert any('C++ in third_party' in finding.message for finding in _infos(findings))


def test_unaccepted_mismatch_is_an_error(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odom', 10)\n")
    contract = _contract(_code_source(), publisher_topic='/vio/odom')

    errors = _errors(check_repository(contract, 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert 'mismatch' in errors[0].message


def test_accepted_mismatch_is_info_only(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odom', 10)\n")
    contract = _contract(_code_source(), publisher_topic='/vio/odom', accepted_mismatch=True)

    findings = check_repository(contract, 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []
    assert any('mismatch' in finding.message for finding in _infos(findings))


def test_unlisted_use_of_contract_topic_is_info_only(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")
    _write(tmp_path, 'tools/echo.py', "self.create_subscription(Odometry, '/vio/odometry', f, 1)\n")

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []
    assert any(finding.file == 'tools/echo.py' for finding in _infos(findings))


def test_unparsable_python_file_is_skipped_with_info(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")
    _write(tmp_path, 'scratch.py', 'def broken(:\n')

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []
    assert any(finding.file == 'scratch.py' for finding in _infos(findings))


def test_third_party_directory_is_not_scanned(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")
    _write(
        tmp_path,
        'third_party/vendor/node.py',
        "self.create_subscription(Odometry, '/vio/odometry', f, 1)\n",
    )

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert not any('third_party' in (finding.file or '') for finding in findings)


def test_editor_lock_file_is_not_scanned(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")
    (tmp_path / '.#vio_publisher.py').symlink_to('user@host.1234')

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert not any('.#' in (finding.file or '') for finding in findings)


def test_unreadable_python_file_is_skipped_with_info(tmp_path):
    _write(tmp_path, 'vio_publisher.py', "self.create_publisher(Odometry, '/vio/odometry', 10)\n")
    (tmp_path / 'dangling.py').symlink_to('missing_target.py')

    findings = check_repository(_contract(_code_source()), 'CINE-Sensing', tmp_path)

    assert _errors(findings) == []
    assert any(finding.file == 'dangling.py' for finding in _infos(findings))


def test_config_that_is_not_utf8_is_an_error(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/vio.json').write_bytes(b'{"vio": "\xff"}')
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'config/vio.json'


def test_profile_that_is_not_utf8_is_an_error(tmp_path):
    _write(tmp_path, 'config/vio.json', json.dumps({'vio': {'odom_topic': '/vio/odometry'}}))
    (tmp_path / 'config/profiles/tune').mkdir(parents=True)
    (tmp_path / 'config/profiles/tune/vio.json').write_bytes(b'{"vio": "\xff"}')
    source = {'kind': 'config', 'file': 'config/vio.json', 'key': ['vio', 'odom_topic']}

    errors = _errors(check_repository(_contract(source), 'CINE-Sensing', tmp_path))

    assert len(errors) == 1
    assert errors[0].file == 'config/profiles/tune/vio.json'

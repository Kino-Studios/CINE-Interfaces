import json

from cine_interfaces.check import main

from cine_interfaces import live_check

CONTRACT = {
    'contract_version': 1,
    'streams': [
        {
            'key': 'position_pose',
            'description': 'VIO pose',
            'message_type': 'geometry_msgs/msg/PoseStamped',
            'direction': 'pi_to_ground',
            'accepted_mismatch': False,
            'publishers': [
                {
                    'repository': 'CINE-Sensing',
                    'node': 'vio_publisher',
                    'topic': '/vio/pose',
                    'source': {'kind': 'code', 'file': 'vio_publisher.py'},
                },
            ],
            'subscribers': [
                {
                    'repository': 'CINE',
                    'node': 'orbit_waypoint_generator',
                    'topic': '/vio/pose',
                    'source': {'kind': 'code', 'file': 'orbit.py'},
                },
            ],
        },
    ],
}


def _setup(tmp_path, publisher_topic='/vio/pose'):
    contract_path = tmp_path / 'contract.json'
    contract_path.write_text(json.dumps(CONTRACT))

    repository_root = tmp_path / 'sensing'
    repository_root.mkdir()
    (repository_root / 'vio_publisher.py').write_text(
        f"self.create_publisher(PoseStamped, '{publisher_topic}', 10)\n",
    )

    return contract_path, repository_root


def test_clean_repository_exits_0(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path)

    exit_code = main(['CINE-Sensing', str(repository_root), '--contract', str(contract_path)])

    assert exit_code == 0
    assert '0 errors' in capsys.readouterr().out


def test_drift_exits_1_and_names_the_file(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path, publisher_topic='/vio/pose_renamed')

    exit_code = main(['CINE-Sensing', str(repository_root), '--contract', str(contract_path)])

    assert exit_code == 1
    assert 'ERROR [position_pose]' in capsys.readouterr().out


def test_unknown_repository_exits_2(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path)

    exit_code = main(['CINE-Sensor', str(repository_root), '--contract', str(contract_path)])

    assert exit_code == 2
    assert 'CINE-Sensor' in capsys.readouterr().err


def test_root_that_is_not_a_directory_exits_2(tmp_path):
    contract_path, _ = _setup(tmp_path)

    exit_code = main(['CINE-Sensing', str(tmp_path / 'missing'), '--contract', str(contract_path)])

    assert exit_code == 2


def test_malformed_contract_exits_2(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path)
    contract_path.write_text('{"contract_version": 1}')

    exit_code = main(['CINE-Sensing', str(repository_root), '--contract', str(contract_path)])

    assert exit_code == 2
    assert 'streams' in capsys.readouterr().err


def test_missing_arguments_exit_2():
    assert main([]) == 2


def test_json_output_is_parseable_and_reports_ok(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path)

    main(['CINE-Sensing', str(repository_root), '--contract', str(contract_path), '--json'])

    report = json.loads(capsys.readouterr().out)
    assert report['ok'] is True
    assert report['errors'] == 0


def test_json_output_lists_drift_findings(tmp_path, capsys):
    contract_path, repository_root = _setup(tmp_path, publisher_topic='/vio/pose_renamed')

    main(['CINE-Sensing', str(repository_root), '--contract', str(contract_path), '--json'])

    report = json.loads(capsys.readouterr().out)
    assert report['ok'] is False
    assert report['findings'][0]['file'] == 'vio_publisher.py'


def test_live_without_ros2_exits_2(tmp_path, capsys, monkeypatch):
    contract_path, _ = _setup(tmp_path)

    def missing_ros2(topic):
        raise FileNotFoundError('ros2')

    monkeypatch.setattr(live_check, 'ros2_topic_info', missing_ros2)

    exit_code = main(['--live', '--contract', str(contract_path)])

    assert exit_code == 2
    assert 'ros2 not found on PATH' in capsys.readouterr().err


def test_live_with_repository_argument_exits_2(tmp_path):
    contract_path, repository_root = _setup(tmp_path)

    exit_code = main(
        ['--live', 'CINE-Sensing', str(repository_root), '--contract', str(contract_path)],
    )

    assert exit_code == 2

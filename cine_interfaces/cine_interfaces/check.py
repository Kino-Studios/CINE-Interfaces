"""Check a repository, or a running ROS 2 graph, against the topic contract.

    python3 -m cine_interfaces.check REPOSITORY ROOT [--contract PATH] [--json]
    python3 -m cine_interfaces.check --live [--strict] [--contract PATH] [--json]

Exit codes: 0 no errors, 1 at least one error finding, 2 the check could not run.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from cine_interfaces import live_check
from cine_interfaces.contract import REPOSITORIES, ContractError, load
from cine_interfaces.static_check import check_repository

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2

_CHECKABLE_REPOSITORIES = tuple(name for name in REPOSITORIES if name != 'external')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python3 -m cine_interfaces.check',
        description='Check a repository, or a running ROS 2 graph, against the topic contract.',
        epilog='Exit codes: 0 no errors, 1 error findings, 2 the check could not run.',
    )

    parser.add_argument(
        'repository',
        nargs='?',
        help=f'repository name as the contract spells it: {", ".join(_CHECKABLE_REPOSITORIES)}',
    )
    parser.add_argument('root', nargs='?', help='path to that repository checkout')
    parser.add_argument(
        '--live',
        action='store_true',
        help='check the running ROS 2 graph instead of a checkout',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='with --live, report accepted mismatches as errors too',
    )
    parser.add_argument('--contract', type=Path, help='contract file (default: the packaged one)')
    parser.add_argument('--json', action='store_true', help='print one JSON report on stdout')

    return parser


def _usage_error(parser: argparse.ArgumentParser, message: str) -> int:
    parser.print_usage(sys.stderr)
    print(f'error: {message}', file=sys.stderr)

    return EXIT_CANNOT_RUN


def _report(findings, as_json: bool) -> int:
    error_count = sum(1 for finding in findings if finding.severity == 'error')
    if as_json:
        report = {
            'ok': error_count == 0,
            'errors': error_count,
            'findings': [asdict(finding) for finding in findings],
        }
        print(json.dumps(report, indent=2))
    else:
        for finding in findings:
            location = f' ({finding.file})' if finding.file else ''
            stream = finding.stream_key or '-'
            print(f'{finding.severity.upper()} [{stream}] {finding.message}{location}')

        print(f'{error_count} errors, {len(findings) - error_count} info')

    return EXIT_FINDINGS if error_count else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()

    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_CANNOT_RUN

    if arguments.live:
        if arguments.repository or arguments.root:
            return _usage_error(parser, '--live takes no REPOSITORY or ROOT')
    else:
        if not arguments.repository or not arguments.root:
            return _usage_error(parser, 'REPOSITORY and ROOT are required without --live')

        if arguments.repository not in _CHECKABLE_REPOSITORIES:
            return _usage_error(
                parser,
                f'unknown repository {arguments.repository!r}; '
                f'expected one of {", ".join(_CHECKABLE_REPOSITORIES)}',
            )

        if not Path(arguments.root).is_dir():
            return _usage_error(parser, f'{arguments.root} is not a directory')

    try:
        contract = load(arguments.contract)
    except (ContractError, OSError) as exc:
        print(f'error: cannot load contract: {exc}', file=sys.stderr)

        return EXIT_CANNOT_RUN

    if arguments.live:
        try:
            findings = live_check.check_live(
                contract,
                topic_info=live_check.ros2_topic_info,
                strict=arguments.strict,
            )
        except FileNotFoundError:
            print('error: ros2 not found on PATH; source a ROS 2 setup first', file=sys.stderr)

            return EXIT_CANNOT_RUN
        except subprocess.TimeoutExpired as exc:
            print(f'error: {exc}; is the ROS 2 daemon responding?', file=sys.stderr)

            return EXIT_CANNOT_RUN
    else:
        findings = check_repository(contract, arguments.repository, Path(arguments.root))

    return _report(findings, arguments.json)


if __name__ == '__main__':
    sys.exit(main())

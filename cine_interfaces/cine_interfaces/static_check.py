"""Compare a repository's code and config against the topic contract, without ROS."""

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cine_interfaces.contract import Contract, Endpoint, Stream

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {'third_party', 'build', 'install', 'log', 'venv', '.venv', '.git', '__pycache__'},
)
_METHOD_BY_ROLE = {'publisher': 'create_publisher', 'subscriber': 'create_subscription'}


@dataclass(frozen=True)
class Finding:
    severity: str
    stream_key: str | None
    message: str
    file: str | None = None


@dataclass(frozen=True)
class _TopicCall:
    method: str
    type_name: str
    topic: str


def _final_name(expression: ast.expr | None) -> str:
    if isinstance(expression, ast.Name):
        return expression.id

    if isinstance(expression, ast.Attribute):
        return expression.attr

    return ''


def _find_topic_calls(tree: ast.AST) -> list[_TopicCall]:
    calls = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue

        if node.func.attr not in _METHOD_BY_ROLE.values():
            continue

        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        type_expression = node.args[0] if node.args else keywords.get('msg_type')
        topic_expression = node.args[1] if len(node.args) > 1 else keywords.get('topic')
        if isinstance(topic_expression, ast.Constant) and isinstance(topic_expression.value, str):
            calls.append(
                _TopicCall(node.func.attr, _final_name(type_expression), topic_expression.value),
            )

    return calls


def _parse_python(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _check_code(stream: Stream, endpoint: Endpoint, role: str, root: Path) -> list[Finding]:
    relative_file = endpoint.source.file
    path = root / relative_file
    if not path.is_file():
        return [
            Finding(
                'error',
                stream.key,
                f'source file not found for {endpoint.node}',
                relative_file,
            ),
        ]

    try:
        tree = _parse_python(path)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return [Finding('error', stream.key, f'source file does not parse: {exc}', relative_file)]

    method = _METHOD_BY_ROLE[role]
    expected_type = stream.message_type.rsplit('/', 1)[-1]
    calls_on_topic = [call for call in _find_topic_calls(tree) if call.topic == endpoint.topic]
    matching_method = [call for call in calls_on_topic if call.method == method]
    if not matching_method:
        other_methods = sorted({call.method for call in calls_on_topic})
        found = f'; found only {", ".join(other_methods)}' if other_methods else ''

        return [
            Finding(
                'error',
                stream.key,
                f'expected {method}({expected_type}, {endpoint.topic!r}) for {endpoint.node}{found}',
                relative_file,
            ),
        ]

    if not any(call.type_name == expected_type for call in matching_method):
        found_types = ', '.join(sorted({call.type_name or '?' for call in matching_method}))

        return [
            Finding(
                'error',
                stream.key,
                f'{method} on {endpoint.topic!r} uses {found_types}, contract says {expected_type}',
                relative_file,
            ),
        ]

    return []


def _value_at(document, key: tuple[str, ...]):
    value = document

    for part in key:
        if not isinstance(value, dict) or part not in value:
            raise KeyError(part)

        value = value[part]

    return value


def _load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _check_config(stream: Stream, endpoint: Endpoint, root: Path) -> list[Finding]:
    relative_file = endpoint.source.file
    key = endpoint.source.key
    key_text = '.'.join(key)
    path = root / relative_file
    if not path.is_file():
        return [
            Finding(
                'error',
                stream.key,
                f'config file not found for {endpoint.node}',
                relative_file,
            ),
        ]

    try:
        base_value = _value_at(_load_json(path), key)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [
            Finding('error', stream.key, f'config file is not valid JSON: {exc}', relative_file),
        ]
    except KeyError:
        return [Finding('error', stream.key, f'config key {key_text} not found', relative_file)]

    findings = []

    if base_value != endpoint.topic:
        findings.append(
            Finding(
                'error',
                stream.key,
                f'config key {key_text} is {base_value!r}, contract says {endpoint.topic!r}',
                relative_file,
            ),
        )

    for profile_path in sorted(path.parent.glob(f'profiles/*/{path.name}')):
        relative_profile = profile_path.relative_to(root).as_posix()

        try:
            profile_value = _value_at(_load_json(profile_path), key)
        except KeyError:
            continue
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            findings.append(
                Finding('error', stream.key, f'profile is not valid JSON: {exc}', relative_profile),
            )
            continue

        if profile_value != endpoint.topic:
            findings.append(
                Finding(
                    'error',
                    stream.key,
                    f'profile sets {key_text} to {profile_value!r}, contract says {endpoint.topic!r}',
                    relative_profile,
                ),
            )

    return findings


def _launch_parameter_values(
    tree: ast.AST,
    executable: str,
    parameter: str,
) -> list[ast.expr] | None:
    """Parameter value expressions for every Node(executable=...) call; None if no such node."""

    values = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _final_name(node.func) != 'Node':
            continue

        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        executable_expression = keywords.get('executable')
        if not (
            isinstance(executable_expression, ast.Constant)
            and executable_expression.value == executable
        ):
            continue

        values = values if values is not None else []
        parameters = keywords.get('parameters')
        if not isinstance(parameters, ast.List):
            continue

        for element in parameters.elts:
            if not isinstance(element, ast.Dict):
                continue

            for key_expression, value_expression in zip(element.keys, element.values, strict=True):
                if isinstance(key_expression, ast.Constant) and key_expression.value == parameter:
                    values.append(value_expression)

    return values


def _check_launch(stream: Stream, endpoint: Endpoint, root: Path) -> list[Finding]:
    source = endpoint.source
    relative_file = source.file
    path = root / relative_file
    if not path.is_file():
        return [
            Finding(
                'error',
                stream.key,
                f'launch file not found for {endpoint.node}',
                relative_file,
            ),
        ]

    try:
        tree = _parse_python(path)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return [Finding('error', stream.key, f'launch file does not parse: {exc}', relative_file)]

    values = _launch_parameter_values(tree, source.executable, source.parameter)
    if values is None:
        return [
            Finding(
                'error',
                stream.key,
                f'no Node(executable={source.executable!r})',
                relative_file,
            ),
        ]

    if not values:
        return [
            Finding(
                'error',
                stream.key,
                f'Node {source.executable!r} sets no {source.parameter!r} parameter',
                relative_file,
            ),
        ]

    findings = []

    for value in values:
        if not isinstance(value, ast.Constant):
            literal = 'a computed value'
        elif value.value != endpoint.topic:
            literal = repr(value.value)
        else:
            continue

        findings.append(
            Finding(
                'error',
                stream.key,
                f'Node {source.executable!r} sets {source.parameter!r} to {literal}, '
                f'contract says {endpoint.topic!r}',
                relative_file,
            ),
        )

    return findings


def _describe_endpoints(stream: Stream) -> str:
    parts = [
        f'{role} {endpoint.repository}/{endpoint.node} on {endpoint.topic}'
        for role, endpoints in (
            ('publisher', stream.publishers),
            ('subscriber', stream.subscribers),
        )
        for endpoint in endpoints
    ]

    if not stream.publishers:
        parts.append('no publisher')

    if not stream.subscribers:
        parts.append('no subscriber')

    return '; '.join(parts)


def _python_files(root: Path):
    for directory, subdirectories, file_names in os.walk(root):
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if name not in EXCLUDED_DIRECTORY_NAMES and not name.startswith('.')
        )

        for file_name in sorted(file_names):
            if file_name.endswith('.py') and not file_name.startswith('.'):
                yield Path(directory) / file_name


def _check_unlisted(contract: Contract, repository: str, root: Path) -> list[Finding]:
    stream_key_by_topic = {}

    for stream in contract.streams:
        for topic in sorted(stream.topic_names):
            stream_key_by_topic.setdefault(topic, stream.key)

    listed = {
        (endpoint.source.file, endpoint.topic)
        for _, endpoint, _ in contract.endpoints_in(repository)
        if endpoint.source.kind == 'code'
    }
    findings = []

    for path in _python_files(root):
        relative_file = path.relative_to(root).as_posix()

        try:
            tree = _parse_python(path)
        except (SyntaxError, ValueError, OSError):
            findings.append(
                Finding('info', None, 'skipped: file cannot be read or parsed', relative_file),
            )
            continue

        for call in _find_topic_calls(tree):
            if call.topic in stream_key_by_topic and (relative_file, call.topic) not in listed:
                findings.append(
                    Finding(
                        'info',
                        stream_key_by_topic[call.topic],
                        f'{call.method} on contract topic {call.topic!r} is not listed in the contract',
                        relative_file,
                    ),
                )

    return findings


def check_repository(contract: Contract, repository: str, repository_root: Path) -> list[Finding]:
    root = Path(repository_root)
    findings = []
    streams_here = []

    for stream, endpoint, role in contract.endpoints_in(repository):
        if stream not in streams_here:
            streams_here.append(stream)

        kind = endpoint.source.kind
        if kind == 'code':
            findings.extend(_check_code(stream, endpoint, role, root))
        elif kind == 'config':
            findings.extend(_check_config(stream, endpoint, root))
        elif kind == 'launch':
            findings.extend(_check_launch(stream, endpoint, root))
        else:
            findings.append(
                Finding(
                    'info',
                    stream.key,
                    f'{role} {endpoint.node} on {endpoint.topic} not checked: {endpoint.source.reason}',
                ),
            )

    for stream in streams_here:
        if stream.is_mismatched:
            severity = 'info' if stream.accepted_mismatch else 'error'
            label = 'accepted mismatch' if stream.accepted_mismatch else 'mismatch'
            findings.append(
                Finding(severity, stream.key, f'{label}: {_describe_endpoints(stream)}'),
            )

    findings.extend(_check_unlisted(contract, repository, root))

    return findings

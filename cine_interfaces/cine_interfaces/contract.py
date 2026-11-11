"""Load and validate the cross-repository topic contract.

The contract lists every ROS 2 topic that crosses Wi-Fi between CINE-Sensing (on the
drone's Raspberry Pi) and CINE (on the ground PC): its message type, who publishes it,
who subscribes, and where each side's topic name comes from in that side's repository.
"""

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

SUPPORTED_CONTRACT_VERSION = 1
REPOSITORIES = ('CINE-Sensing', 'CINE', 'external')
DIRECTIONS = ('pi_to_ground', 'ground_to_pi')

_STREAM_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')
_MESSAGE_TYPE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*/msg/[A-Z][A-Za-z0-9]*$')
_TOPIC_PATTERN = re.compile(r'^/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*$')

_DOCUMENT_FIELDS = {'contract_version', 'streams'}
_STREAM_FIELDS = {
    'key',
    'description',
    'message_type',
    'direction',
    'accepted_mismatch',
    'publishers',
    'subscribers',
}
_ENDPOINT_FIELDS = {'repository', 'node', 'topic', 'source'}
_SOURCE_FIELDS_BY_KIND = {
    'code': {'kind', 'file'},
    'config': {'kind', 'file', 'key'},
    'launch': {'kind', 'file', 'executable', 'parameter'},
    'unchecked': {'kind', 'reason'},
}


class ContractError(ValueError):
    """The contract document is malformed; the message names the stream and field."""


@dataclass(frozen=True)
class Source:
    kind: str
    file: str | None = None
    key: tuple[str, ...] | None = None
    executable: str | None = None
    parameter: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Endpoint:
    repository: str
    node: str
    topic: str
    source: Source


@dataclass(frozen=True)
class Stream:
    key: str
    description: str
    message_type: str
    direction: str
    accepted_mismatch: bool
    publishers: tuple[Endpoint, ...]
    subscribers: tuple[Endpoint, ...]

    @property
    def topic_names(self) -> frozenset[str]:
        return frozenset(endpoint.topic for endpoint in self.publishers + self.subscribers)

    @property
    def is_mismatched(self) -> bool:
        return len(self.topic_names) > 1 or not self.publishers or not self.subscribers


@dataclass(frozen=True)
class Contract:
    version: int
    streams: tuple[Stream, ...]

    def stream(self, key: str) -> Stream:
        for stream in self.streams:
            if stream.key == key:
                return stream

        raise KeyError(key)

    def endpoints_in(self, repository: str) -> list[tuple[Stream, Endpoint, str]]:
        found = []

        for stream in self.streams:
            for endpoint in stream.publishers:
                if endpoint.repository == repository:
                    found.append((stream, endpoint, 'publisher'))

            for endpoint in stream.subscribers:
                if endpoint.repository == repository:
                    found.append((stream, endpoint, 'subscriber'))

        return found


def _check_fields(mapping, allowed: set[str], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ContractError(f'{where}: expected an object, got {type(mapping).__name__}')

    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ContractError(f'{where}: unknown field(s) {", ".join(unknown)}')

    missing = sorted(allowed - set(mapping))
    if missing:
        raise ContractError(f'{where}: missing field(s) {", ".join(missing)}')


def _require_string(value, field: str, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f'{where}: field {field} must be a non-empty string')

    return value


def _parse_source(document, where: str) -> Source:
    if not isinstance(document, dict) or 'kind' not in document:
        raise ContractError(f'{where}: source needs a kind')

    kind = document['kind']
    if kind not in _SOURCE_FIELDS_BY_KIND:
        raise ContractError(
            f'{where}: source kind {kind!r} is not one of {", ".join(_SOURCE_FIELDS_BY_KIND)}',
        )

    _check_fields(document, _SOURCE_FIELDS_BY_KIND[kind], f'{where} source')
    key = None

    if kind == 'config':
        key = document['key']
        if not isinstance(key, list) or not key or not all(isinstance(part, str) for part in key):
            raise ContractError(f'{where}: config source key must be a non-empty list of strings')

        key = tuple(key)

    for field in ('file', 'executable', 'parameter', 'reason'):
        if field in document:
            _require_string(document[field], field, where)

    return Source(
        kind=kind,
        file=document.get('file'),
        key=key,
        executable=document.get('executable'),
        parameter=document.get('parameter'),
        reason=document.get('reason'),
    )


def _parse_endpoint(document, where: str) -> Endpoint:
    _check_fields(document, _ENDPOINT_FIELDS, where)
    repository = document['repository']
    if repository not in REPOSITORIES:
        raise ContractError(
            f'{where}: repository {repository!r} is not one of {", ".join(REPOSITORIES)}',
        )

    topic = _require_string(document['topic'], 'topic', where)
    if not _TOPIC_PATTERN.match(topic):
        raise ContractError(f'{where}: topic {topic!r} must be absolute, with no trailing slash')

    source = _parse_source(document['source'], where)
    if repository == 'external' and source.kind != 'unchecked':
        raise ContractError(f'{where}: an external endpoint must have an unchecked source')

    return Endpoint(
        repository=repository,
        node=_require_string(document['node'], 'node', where),
        topic=topic,
        source=source,
    )


def _parse_stream(document, index: int) -> Stream:
    key = document.get('key') if isinstance(document, dict) else None
    where = f'stream {key}' if isinstance(key, str) else f'stream #{index}'
    _check_fields(document, _STREAM_FIELDS, where)

    if not isinstance(key, str) or not _STREAM_KEY_PATTERN.match(key):
        raise ContractError(f'{where}: key must be lower_snake_case')

    message_type = _require_string(document['message_type'], 'message_type', where)
    if not _MESSAGE_TYPE_PATTERN.match(message_type):
        raise ContractError(
            f'{where}: message_type {message_type!r} must look like package/msg/Type',
        )

    if document['direction'] not in DIRECTIONS:
        raise ContractError(f'{where}: direction must be one of {", ".join(DIRECTIONS)}')

    if not isinstance(document['accepted_mismatch'], bool):
        raise ContractError(f'{where}: accepted_mismatch must be true or false')

    endpoints_by_role = {}

    for role in ('publishers', 'subscribers'):
        if not isinstance(document[role], list):
            raise ContractError(f'{where}: {role} must be a list')

        endpoints_by_role[role] = tuple(
            _parse_endpoint(endpoint, f'{where} {role}[{position}]')
            for position, endpoint in enumerate(document[role])
        )

    return Stream(
        key=key,
        description=_require_string(document['description'], 'description', where),
        message_type=message_type,
        direction=document['direction'],
        accepted_mismatch=document['accepted_mismatch'],
        publishers=endpoints_by_role['publishers'],
        subscribers=endpoints_by_role['subscribers'],
    )


def parse(document: dict) -> Contract:
    _check_fields(document, _DOCUMENT_FIELDS, 'contract')

    if document['contract_version'] != SUPPORTED_CONTRACT_VERSION:
        raise ContractError(
            f'contract: contract_version {document["contract_version"]!r} is not supported '
            f'(expected {SUPPORTED_CONTRACT_VERSION})',
        )

    if not isinstance(document['streams'], list):
        raise ContractError('contract: streams must be a list')

    streams = tuple(
        _parse_stream(stream, index) for index, stream in enumerate(document['streams'])
    )
    seen_keys = set()

    for stream in streams:
        if stream.key in seen_keys:
            raise ContractError(f'stream {stream.key}: duplicate stream key')

        seen_keys.add(stream.key)

    return Contract(version=document['contract_version'], streams=streams)


def load(path: Path | None = None) -> Contract:
    if path is None:
        text = resources.files('cine_interfaces').joinpath('contract.json').read_text()
    else:
        text = Path(path).read_text()

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f'contract is not valid JSON: {exc}') from exc

    return parse(document)

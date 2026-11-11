"""Compare a running ROS 2 graph against the topic contract."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from cine_interfaces.contract import Contract
from cine_interfaces.static_check import Finding

_GRAPH_TYPE_BY_ROLE = {'publisher': 'PUBLISHER', 'subscriber': 'SUBSCRIPTION'}
_QUERY_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class GraphEndpoint:
    node_name: str
    node_namespace: str
    topic_type: str
    endpoint_type: str


def parse_topic_info(text: str) -> list[GraphEndpoint]:
    """Read the endpoint blocks out of `ros2 topic info --verbose` output."""

    endpoints = []
    block = {}

    for line in text.splitlines() + ['Node name: ']:
        if line.startswith((' ', '\t')) or ':' not in line:
            continue

        field, _, value = line.partition(':')
        field, value = field.strip(), value.strip()
        if field == 'Node name':
            if {'Node name', 'Topic type', 'Endpoint type'} <= set(block):
                endpoints.append(
                    GraphEndpoint(
                        node_name=block['Node name'],
                        node_namespace=block.get('Node namespace', ''),
                        topic_type=block['Topic type'],
                        endpoint_type=block['Endpoint type'],
                    ),
                )

            block = {}

        block[field] = value

    return endpoints


def ros2_topic_info(topic: str) -> str | None:
    """Return `ros2 topic info --verbose` output, or None when the graph lacks the topic.

    Raises FileNotFoundError when `ros2` is not on PATH.
    """

    result = subprocess.run(
        ['ros2', 'topic', 'info', '--verbose', topic],
        capture_output=True,
        text=True,
        timeout=_QUERY_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        return None

    return result.stdout


def _has_endpoint(graph_endpoints, endpoint_type: str, message_type: str) -> bool:
    return any(
        graph_endpoint.endpoint_type == endpoint_type and graph_endpoint.topic_type == message_type
        for graph_endpoint in graph_endpoints
    )


def check_live(
    contract: Contract,
    topic_info: Callable[[str], str | None] = ros2_topic_info,
    strict: bool = False,
) -> list[Finding]:
    endpoints_by_topic = {}
    findings = []

    for stream in contract.streams:
        for role, endpoints in (
            ('publisher', stream.publishers),
            ('subscriber', stream.subscribers),
        ):
            for endpoint in endpoints:
                if endpoint.repository == 'external':
                    continue

                if endpoint.topic not in endpoints_by_topic:
                    text = topic_info(endpoint.topic)
                    endpoints_by_topic[endpoint.topic] = (
                        parse_topic_info(text) if text is not None else None
                    )

                graph_endpoints = endpoints_by_topic[endpoint.topic]
                wanted_type = _GRAPH_TYPE_BY_ROLE[role]
                if graph_endpoints is None:
                    problem = f'topic {endpoint.topic} is not in the graph'
                elif not _has_endpoint(graph_endpoints, wanted_type, stream.message_type):
                    problem = (
                        f'no {wanted_type} of {stream.message_type} on {endpoint.topic} '
                        f'for {endpoint.repository}/{endpoint.node}'
                    )
                elif role == 'subscriber' and not _has_endpoint(
                    graph_endpoints,
                    'PUBLISHER',
                    stream.message_type,
                ):
                    problem = (
                        f'no PUBLISHER of {stream.message_type} on {endpoint.topic}, '
                        'so nothing reaches this subscription'
                    )
                else:
                    continue

                severity = 'info' if stream.accepted_mismatch and not strict else 'error'
                findings.append(Finding(severity, stream.key, f'{role} {endpoint.node}: {problem}'))

    return findings

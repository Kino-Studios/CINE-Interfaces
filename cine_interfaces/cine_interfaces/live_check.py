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


def _matching_endpoints(graph_endpoints, endpoint_type: str, message_type: str) -> list:
    return [
        graph_endpoint
        for graph_endpoint in graph_endpoints
        if graph_endpoint.endpoint_type == endpoint_type
        and graph_endpoint.topic_type == message_type
    ]


def _is_contract_node(graph_node_name: str, contract_node_name: str) -> bool:
    return graph_node_name == contract_node_name or graph_node_name.endswith(
        f'_{contract_node_name}',
    )


def _missing_node_problem(graph_endpoints, endpoint, wanted_type, message_type) -> str | None:
    """Describe why `endpoint.node` has no `wanted_type` endpoint, or None when it has one.

    Only the node name is compared, not its namespace, and a name that adds an
    underscore-separated prefix such as `drone_0_` still counts, so per-drone launches pass.
    """

    candidates = _matching_endpoints(graph_endpoints, wanted_type, message_type)
    if any(_is_contract_node(candidate.node_name, endpoint.node) for candidate in candidates):
        return None

    problem = (
        f'no {wanted_type} of {message_type} on {endpoint.topic} '
        f'for {endpoint.repository}/{endpoint.node}'
    )

    if candidates:
        other_nodes = ', '.join(sorted({candidate.node_name for candidate in candidates}))
        problem += f' (found only: {other_nodes})'

    return problem


def check_live(
    contract: Contract,
    topic_info: Callable[[str], str | None] = ros2_topic_info,
    strict: bool = False,
    mode: str = 'hardware',
) -> list[Finding]:
    endpoints_by_topic = {}
    findings = []

    for stream in contract.streams:
        if mode not in stream.modes:
            continue

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
                elif node_problem := _missing_node_problem(
                    graph_endpoints,
                    endpoint,
                    wanted_type,
                    stream.message_type,
                ):
                    problem = node_problem
                elif role == 'subscriber' and not _matching_endpoints(
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

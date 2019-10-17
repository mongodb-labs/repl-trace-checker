import dataclasses
from collections.abc import Generator, Mapping, Sequence
from typing import Tuple

from bson import Timestamp

from repl_checker_dataclass import repl_checker_dataclass


@repl_checker_dataclass(unsafe_hash=True)
class OplogEntry:
    term: int

    def to_tla(self):
        return python_to_tla(dataclasses.asdict(self))


@repl_checker_dataclass(unsafe_hash=True)
class CommitPoint:
    term: int
    index: int

    def to_tla(self):
        return python_to_tla(dataclasses.asdict(self))


@repl_checker_dataclass(unsafe_hash=True)
class SystemState:
    n_servers: int

    globalCurrentTerm: int
    """The globalCurrentTerm in the TLA+ spec."""

    log: Tuple[Tuple[OplogEntry]]
    """A list of oplogs, one per server."""

    state: Tuple[str]
    """A list of states, either Leader or Follower, one per server."""

    commitPoint: Tuple[CommitPoint]
    """Each server's view of the commit point, one OplogEntry per server."""

    def __post_init__(self):
        assert len(self.log) == self.n_servers
        assert len(self.state) == self.n_servers
        assert len(self.commitPoint) == self.n_servers

    __pretty_template__ = """global term: {{ globalCurrentTerm }}
{% for i in range(n_servers) -%}
server {{ i }}: state={{ state[i] }}, commit point={{ commitPoint[i] }},
{%- if log[i] %}
 log={{ log[i] | join(', ') }}
{%- else %}
 log=empty
{%- endif -%}
{%- if loop.nextitem -%}
{{ '\n' }}
{%- endif -%}
{%- endfor -%}"""

    @classmethod
    def tla_variable_names(cls):
        return ('globalCurrentTerm', 'log', 'state', 'commitPoint')

    def to_tla(self):
        return python_to_tla((getattr(self, name)
                              for name in self.tla_variable_names()))


class PortMapper:
    """Maps port numbers to server ids, 0-indexed."""

    def __init__(self):
        self.port_to_server = {}
        self.next_server_id = 0

    def get_server_id(self, port):
        if port not in self.port_to_server:
            self.port_to_server[port] = self.next_server_id
            self.next_server_id += 1

        return self.port_to_server[port]


class OplogIndexMapper:
    """Maps MongoDB oplog timestamps to TLA+ log indexes, 0-indexed."""

    def __init__(self):
        self._ts_to_index = {Timestamp(0, 0): 0}

    def set_index(self, timestamp, index):
        if timestamp in self._ts_to_index:
            assert self._ts_to_index[timestamp] == index
        else:
            self._ts_to_index[timestamp] = index

    def get_index(self, timestamp):
        return self._ts_to_index[timestamp]


def python_to_tla(data):
    """Convert a Python object to a TLA+ expression string."""
    if hasattr(data, 'to_tla'):
        return data.to_tla()

    # str is a Sequence, so check for str before Sequence.
    if isinstance(data, str):
        return f'"{data}"'

    if isinstance(data, int):
        return repr(data)

    if isinstance(data, (Sequence, Generator)):
        return f'<<{",".join(python_to_tla(i) for i in data)}>>'

    if isinstance(data, Mapping):
        def gen():
            for key, value in data.items():
                yield f'{key} |-> {value}'

        return f'[{", ".join(gen())}]'

    raise TypeError(f'Cannot convert {data!r} to TLA+ notation')

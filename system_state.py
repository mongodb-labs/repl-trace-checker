from __future__ import annotations

import dataclasses
import enum
from collections.abc import Generator, Mapping, Sequence
from typing import Optional, Set, Tuple

from repl_checker_dataclass import repl_checker_dataclass


class ServerState(enum.Enum):
    Leader = enum.auto()
    Follower = enum.auto()

    def to_tla(self):
        return python_to_tla(self.name)

    def __str__(self):
        return self.name.rjust(ServerState._max_name_length)


ServerState._max_name_length = max(len(e.name) for e in ServerState)


@repl_checker_dataclass(unsafe_hash=True)
class OpTime:
    term: int
    timestamp: int
    """Timestamp as unsigned long long."""


@repl_checker_dataclass(unsafe_hash=True)
class OplogEntry:
    term: int
    index: int
    # Self ref requires future import of annotations.
    previous: Optional[OplogEntry]

    def to_tla(self):
        return python_to_tla({'term': self.term})

    def get_complete_log(self):
        """Tuple of all oplog entries, ending in self."""
        # Avoid recursion, we could hit Python's recursion limit.
        oplog = []
        current = self
        while current:
            oplog.append(current)
            current = current.previous

        return tuple(reversed(oplog))


@repl_checker_dataclass(unsafe_hash=True)
class CommitPoint:
    term: int
    index: int

    def is_null(self):
        return self.term == 0 and self.index == 0

    def to_tla(self):
        return python_to_tla(dataclasses.asdict(self))


def _raft_mongo_variable():
    return dataclasses.field(metadata={'raft_mongo': True, 'tla': True})


def _tla_variable():
    return dataclasses.field(metadata={'tla': True})


@repl_checker_dataclass(unsafe_hash=True)
class SystemState:
    n_servers: int

    action: str = _tla_variable()
    """The TLA+ action that led to this state."""

    committedEntries: Set[CommitPoint] = _raft_mongo_variable()
    """The set of log entries that have been acknowledged as committed."""

    currentTerm: Tuple[int] = _raft_mongo_variable()
    """The term number known by each server."""

    log: Tuple[Tuple[OplogEntry]] = _raft_mongo_variable()
    """A list of oplogs, one per server."""

    state: Tuple[ServerState] = _raft_mongo_variable()
    """A list of states, either Leader or Follower, one per server."""

    commitPoint: Tuple[CommitPoint] = _raft_mongo_variable()
    """Each server's view of the commit point, one OplogEntry per server."""

    serverLogLocation: str = _tla_variable()
    """Filename:line of the mongod log that generated this state."""

    def __post_init__(self):
        assert len(self.log) == self.n_servers
        assert len(self.state) == self.n_servers
        assert len(self.commitPoint) == self.n_servers

    __pretty_template__ = """{% for i in range(n_servers) -%}
server {{ i }}: state={{ state[i] }}, term={{ currentTerm[i] }}, commit point={{ commitPoint[i] }},
{%- if log[i] %}
 log={{ log[i] | oplog }}
{%- else %}
 log=empty
{%- endif -%}
{%- if loop.nextitem -%}
{{ '\n' }}
{%- endif -%}
{%- endfor -%}"""

    @classmethod
    def raft_mongo_variables(cls):
        return tuple((f.name for f in dataclasses.fields(cls)
                      if f.metadata.get('raft_mongo')))

    @classmethod
    def all_tla_variables(cls):
        return tuple((f.name for f in dataclasses.fields(cls)
                      if f.metadata.get('tla')))

    def to_tla(self):
        return python_to_tla((getattr(self, name)
                              for name in self.all_tla_variables()))

    @property
    def max_oplog_len(self):
        return max(len(log) for log in self.log)


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


def python_to_tla(data):
    """Convert a Python object to a TLA+ expression string."""
    if hasattr(data, 'to_tla'):
        return data.to_tla()

    if isinstance(data, bool):
        return 'TRUE' if data else 'FALSE'

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
                yield f'{key} |-> {python_to_tla(value)}'

        return f'[{", ".join(gen())}]'

    if isinstance(data, set):
        def gen():
            for value in data:
                yield python_to_tla(value)

        return f'{{{", ".join(gen())}}}'

    raise TypeError(f'Cannot convert {data!r} to TLA+ notation')

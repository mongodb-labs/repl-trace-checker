from dataclasses import dataclass
from typing import Tuple


@dataclass(unsafe_hash=True)
class OplogEntry:
    term: int
    index: int


@dataclass(unsafe_hash=True)
class SystemState:
    n_servers: int

    global_current_term: int
    """The globalCurrentTerm in the TLA+ spec."""

    log: Tuple[Tuple[OplogEntry]]
    """A list of oplogs, one per server."""

    server_state: Tuple[str]
    """A list of states, either Leader or Follower, one per server."""

    commit_point: Tuple[OplogEntry]
    """Each server's view of the commit point, one OplogEntry per server."""

    def __post_init__(self):
        assert len(self.log) == self.n_servers
        assert len(self.server_state) == self.n_servers
        assert len(self.commit_point) == self.n_servers


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
        self.timestamp_to_index = {}
        self.next_index = 0

    def get_index(self, timestamp):
        if timestamp not in self.timestamp_to_index:
            self.timestamp_to_index[timestamp] = self.next_index
            self.next_index += 1

        return self.timestamp_to_index[timestamp]

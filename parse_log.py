"""
Parse replica set member's mongod.log. The member must have verbose logging
enabled like:

    db.adminCommand({
        setParameter: 1,
        logComponentVerbosity: {tlaPlusTrace: 1}
    })
"""
import datetime
import heapq
import re
import sys
from json import JSONDecodeError

from bson import json_util, Timestamp  # pip install pymongo

from repl_checker_dataclass import repl_checker_dataclass
from system_state import OplogEntry, CommitPoint, ServerState

# Match lines like:
# 2019-07-16T12:24:41.964-0400 I  TLA_PLUS_TRACE [replexec-0]
#   {"action": "BecomePrimaryByMagic", ...}
line_pat = re.compile(
    r'(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}[+-]\d{4})'
    r'.+? TLA_PLUS \[(?P<threadName>[\w\-\d]+)] '
    r'(?P<json>{.*})')


def parse_log_timestamp(timestamp_str):
    return datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f%z')


@repl_checker_dataclass(order=True)
class LogLine:
    # Ordered so that a sequence of LogLines are sorted by timestamp.
    timestamp: datetime.datetime
    location: str
    line: str
    obj: dict


def merge_log_streams(streams):
    """Merge logs, sorting by timestamp."""

    def gen(stream):
        line_number = 0
        for line in stream:
            line_number += 1
            match = line_pat.match(line)
            if not match:
                continue

            timestamp = parse_log_timestamp(match.group('timestamp'))
            try:
                # json_util converts e.g. $numberLong to Python int.
                obj = json_util.loads(match.group('json'))
            except JSONDecodeError as exc:
                print(f"Invalid JSON in {stream.name}:{line_number}"
                      f" {exc.msg} in column {exc.colno}:\n"
                      f"{match.group('json')}")
                sys.exit(2)

            # Yield tuples
            yield LogLine(timestamp=timestamp,
                          location=f'{stream.name}:{line_number}',
                          line=line,
                          obj=obj)

    return heapq.merge(*map(gen, streams))


@repl_checker_dataclass
class LogEvent:
    timestamp: datetime.datetime
    """The server log timestamp."""
    location: str
    """File name and line number, like 'file.log:123'."""
    line: str
    """The text of the server log line"""
    action: str
    """The action (in TLA+ spec terms) the server is taking."""
    server_id: int
    """The server's id (0-indexed)."""
    currentTerm: int
    """The server's view of the term.
    
    NOTE: The implementation's term starts at -1, then increases to 1, then
    increments normally. We treat -1 as if it were 0.
    """
    state: ServerState
    """The server's replica set member state."""
    commitPoint: CommitPoint
    """The server's view of the commit point."""
    log: tuple
    """The server's oplog."""

    __pretty_template__ = """{{ location }} at {{ timestamp | mongo_dt }}
{{ action }} server_id={{ server_id }} state={{ state.name }} term={{ currentTerm }}
commit point: {{ commitPoint }}
log: {{ log | oplog }}"""


def _fixup_term(term):
    # What the implementation calls -1, the spec calls 0.
    return 0 if term == -1 else term


def _as_tuple(optime_dict):
    return _fixup_term(optime_dict['t']), optime_dict['ts']


class OplogIndexMapper:
    """Maps MongoDB oplog timestamps to TLA+ log indexes, 0-indexed."""

    def __init__(self):
        self._optime_to_index = {(0, Timestamp(0, 0)): 0}
        self._empty = True

    def update(self, oplog):
        # JSON oplog is a list of optimes with timestamp "ts" and term "t", like
        # [{ts: Timestamp(1234, 1}, t: 1}, ...].
        if not oplog:
            return

        start = _as_tuple(oplog[0])
        if self._empty:
            offset = 0
        elif start in self._optime_to_index:
            offset = self._optime_to_index[start]
        else:
            raise Exception(
                f"Can't map optimes to TLA+ log indexes, encountered"
                f" non-overlapping oplog segment starting at {start}. Saw"
                f" optimes from {min(self._optime_to_index)} to"
                f" {max(self._optime_to_index)} so far.")

        for i in range(len(oplog)):
            index = i + offset
            optime = _as_tuple(oplog[i])
            if optime in self._optime_to_index:
                assert self._optime_to_index[optime] == index
            else:
                self._optime_to_index[optime] = index

        self._empty = False

    def get_index(self, optime):
        return self._optime_to_index[_as_tuple(optime)]


def parse_log_line(log_line, port_mapper, oplog_index_mapper):
    """Transform a LogLine into a LogEvent."""
    try:
        # Generic logging is in "trace", RaftMongo.tla-specific in "raft_mongo".
        trace = log_line.obj
        raft_mongo = trace['state']
        port = int(trace['host'].split(':')[1])

        log = tuple(OplogEntry(term=entry['t']) for entry in raft_mongo['log'])

        # Update timestamp -> index map, which we use below for CommitPoint.
        oplog_index_mapper.update(raft_mongo['log'])

        commitPoint = CommitPoint(
            term=_fixup_term(raft_mongo['commitPoint']['t']),
            index=oplog_index_mapper.get_index(raft_mongo['commitPoint']))

        return LogEvent(timestamp=log_line.timestamp,
                        location=log_line.location,
                        line=log_line.line,
                        action=trace['action'],
                        server_id=port_mapper.get_server_id(port),
                        currentTerm=_fixup_term(raft_mongo['currentTerm']),
                        state=ServerState[raft_mongo['serverState']],
                        commitPoint=commitPoint,
                        log=log)
    except Exception:
        print(f'Exception at {log_line.location}: {log_line.line}',
              file=sys.stderr)
        raise

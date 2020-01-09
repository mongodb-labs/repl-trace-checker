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
from typing import Dict

import orjson

from repl_checker_dataclass import repl_checker_dataclass
from system_state import OplogEntry, CommitPoint, ServerState, OpTime

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


def parse_log(stream):
    """Yield LogLines parsed from a log file stream."""

    def gen():
        line_number = 0
        for line in stream:
            line_number += 1
            match = line_pat.match(line)
            if not match:
                continue

            timestamp = parse_log_timestamp(match.group('timestamp'))
            try:
                obj = orjson.loads(match.group('json'))
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

    return list(gen())


def merge_log_streams(streams):
    """Merge logs, sorting by timestamp."""
    return heapq.merge(*map(parse_log, streams))


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
{{ action }} server_id={{ server_id }} state={{ state.name }} term={{ term }}
commit point: {{ commitPoint }}
log: {{ log | oplog }}"""


def _parse_term(term):
    # What the implementation calls -1, the spec calls 0.
    return 0 if term == '-1' else int(term)


def _parse_optime(obj):
    """ Convert an OpTime from JSON."""
    # obj is like:
    #
    #     {ts: {$timestamp: {t: 1578078726, i: 5}}, t: {$numberLong: '1'}}
    #
    # PyMongo's bson.json_util converts timestamp and numberLong objects but
    # it's more performant to special-case that logic here.
    as_int = obj['ts']['$timestamp']['t'] << 32 | obj['ts']['$timestamp']['i']
    return OpTime(term=_parse_term(obj['t']['$numberLong']), timestamp=as_int)


class OplogIndexMapper:
    """Maps MongoDB oplog timestamps to TLA+ log indexes, 0-indexed."""
    _optime_to_entry: Dict[OpTime, OplogEntry]

    def __init__(self):
        # The "null" commitPoint is (0, 0). Fake an OplogEntry for it.
        null_entry = OplogEntry(term=0, index=0, previous=None)
        self._optime_to_entry = {OpTime(0, 0): null_entry}
        self._empty = True

    def get_entry(self, optime):
        """Get OplogEntry for OpTime."""
        return self._optime_to_entry[optime]

    def add_entry(self, optime, entry):
        """Add mapping from OpTime to OplogEntry object."""
        if optime in self._optime_to_entry:
            old_entry = self._optime_to_entry[optime]
            assert old_entry == entry
        else:
            self._optime_to_entry[optime] = entry
        self._empty = False

    @property
    def empty(self):
        return self._empty


def parse_log_line(log_line, port_mapper, oplog_index_mapper):
    """Transform a LogLine into a LogEvent."""
    try:
        # Generic logging is in "trace", RaftMongo.tla-specific in "raft_mongo".
        trace = log_line.obj
        port = int(trace['host'].split(':')[1])
        raft_mongo = trace['state']
        optimes = [_parse_optime(optime) for optime in raft_mongo['log']]

        if optimes:
            if oplog_index_mapper.empty:
                # Add first entry at index 1.
                oplog_index_mapper.add_entry(
                    optimes[0],
                    OplogEntry(term=optimes[0].term,
                               index=1,
                               previous=None))

            # Iterate consecutive pairs of entries.
            for optime_a, optime_b in zip(optimes, optimes[1:]):
                # The previous optime must already have an OplogEntry.
                previous = oplog_index_mapper.get_entry(optime_a)
                oplog_index_mapper.add_entry(
                    optime_b,
                    OplogEntry(term=optime_b.term,
                               index=previous.index + 1,
                               previous=previous))

            log = oplog_index_mapper.get_entry(optimes[-1]).get_complete_log()
        else:
            log = ()

        commitPointOpTime = _parse_optime(raft_mongo['commitPoint'])
        commitPoint = CommitPoint(
            term=commitPointOpTime.term,
            index=oplog_index_mapper.get_entry(commitPointOpTime).index)

        return LogEvent(
            timestamp=log_line.timestamp,
            location=log_line.location,
            line=log_line.line,
            action=trace['action'],
            server_id=port_mapper.get_server_id(port),
            currentTerm=_parse_term(raft_mongo['term']['$numberLong']),
            state=ServerState[raft_mongo['serverState']],
            commitPoint=commitPoint,
            log=log)
    except Exception:
        print(f'Exception at {log_line.location}: {log_line.line}',
              file=sys.stderr)
        raise

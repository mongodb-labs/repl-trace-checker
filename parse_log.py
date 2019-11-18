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

from bson import json_util  # pip install pymongo

from repl_checker_dataclass import repl_checker_dataclass
from system_state import OplogEntry, CommitPoint, ServerState

# Match lines like:
# 2019-07-16T12:24:41.964-0400 I  TLA_PLUS_TRACE [replexec-0]
#   {"action": "BecomePrimaryByMagic", ...}
line_pat = re.compile(
    r'(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}[+-]\d{4})'
    r'.+? TLA_PLUS .+? '
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
                print(f"Invalid JSON in {stream.name}:"
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
    """Line number."""
    line: str
    """The text of the server log line"""
    action: str
    """The action (in TLA+ spec terms) the server is taking."""
    server_id: int
    """The server's id (0-indexed)."""
    term: int
    """The server's view of the term."""
    state: ServerState
    """The server's replica set member state."""
    commitPoint: CommitPoint
    """The server's view of the commit point."""
    log: tuple
    """The server's oplog."""

    __pretty_template__ = """{{ location }} at {{ timestamp }}
{{ action }} server_id={{ server_id }} state={{ state.name }} term={{ term }}
commit point: {{ commitPoint }}
log: {{ log | join(', ') }}"""


def parse_oplog(obj, oplog_index_mapper):
    """Parse a TLA+ oplog from a JSON-parsed mongod log message.

    obj is like {'0': {op: 'i', ...}, 1: {...}}.
    """

    def gen():
        for index, entry in sorted(obj.items(), key=lambda item: int(item[0])):
            # TODO: do we actually need oplog_index_mapper?
            oplog_index_mapper.set_index(entry['ts'], int(index))
            yield OplogEntry(term=entry['term'])

    return tuple(gen())


def parse_log_line(log_line, port_mapper, oplog_index_mapper):
    """Transform a LogLine into a LogEvent."""
    try:
        obj = log_line.obj
        # MongoDB terms start at -1.
        term = obj['commitPoint']['t']
        commitPoint = CommitPoint(
            term=term,
            index=oplog_index_mapper.get_index(obj['commitPoint']['ts']))

        return LogEvent(timestamp=log_line.timestamp,
                        location=log_line.location,
                        line=log_line.line,
                        action=obj['action'],
                        server_id=port_mapper.get_server_id(obj['myPort']),
                        term=obj['term'],
                        state=ServerState[obj['serverState']],
                        commitPoint=commitPoint,
                        log=parse_oplog(obj['log'], oplog_index_mapper))
    except Exception:
        print('Exception parsing line: {!r}'.format(log_line))
        raise

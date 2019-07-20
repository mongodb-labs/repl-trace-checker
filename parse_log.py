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

from bson import json_util  # pip install pymongo

from repl_checker_dataclass import repl_checker_dataclass
from system_state import OplogEntry

# Match lines like:
# 2019-07-16T12:24:41.964-0400 I  TLA_PLUS_TRACE [replexec-0]
#   {"action": "BecomePrimaryByMagic", ...}
line_pat = re.compile(
    r'(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}[+-]\d{4})'
    r'.+?TLA_PLUS_TRACE.+? '
    r'(?P<json>{.*})')


def parse_log_timestamp(timestamp_str):
    return datetime.datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%f%z')


def merge_log_streams(streams):
    """Merge logs, sorting by timestamp."""

    def gen(stream):
        for line in stream:
            match = line_pat.match(line)
            if not match:
                continue

            timestamp = parse_log_timestamp(match.group('timestamp'))
            # Yield (timestamp, line) tuples so heapq.merge sorts by timestamp.
            yield timestamp, line

    for _, line in heapq.merge(*map(gen, streams)):
        yield line


@repl_checker_dataclass
class LogEvent:
    timestamp: datetime.datetime
    action: str
    server_id: int
    term: int
    server_state: str
    commit_point: OplogEntry
    log: tuple


def parse_oplog(obj, oplog_index_mapper):
    """Parse a TLA+ oplog from a JSON-parsed mongod log message.

    obj is like {'0': {op: 'i', ...}, 1: {...}}.
    """

    def gen():
        for index, entry in sorted(obj.items(), key=lambda item: int(item[0])):
            oplog_index_mapper.set_index(entry['ts'], int(index))
            yield OplogEntry(term=entry['t'], index=int(index))

    return tuple(gen())


def parse_log_line(line, port_mapper, oplog_index_mapper):
    try:
        match = line_pat.match(line)
        if match:
            timestamp = parse_log_timestamp(match.group('timestamp'))
            # json_util converts e.g. $numberLong to Python int.
            obj = json_util.loads(match.group('json'))
            # MongoDB terms start at -1.
            # TODO: Is this right?
            term = max(obj['commitPoint']['t'], 0)
            commit_point = OplogEntry(
                term=term,
                index=oplog_index_mapper.get_index(obj['commitPoint']['ts'])
            )

            if obj['serverState'] not in ('PRIMARY', 'SECONDARY'):
                raise ValueError(
                    f"Illegal server state {obj['serverState']}, only PRIMARY"
                    f" or SECONDARY are allowed in log messages")

            server_state = (
                'Leader' if obj['serverState'] == 'PRIMARY' else 'Follower')

            return LogEvent(
                timestamp=timestamp,
                action=obj['action'],
                server_id=port_mapper.get_server_id(obj['myPort']),
                term=obj['term'],
                server_state=server_state,
                commit_point=commit_point,
                log=parse_oplog(obj['log'], oplog_index_mapper))
    except Exception:
        print('Exception parsing line: {!r}'.format(line))
        raise

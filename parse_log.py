"""
Parse replica set member's mongod.log. The member must have verbose logging
enabled like:

    db.adminCommand({
        setParameter: 1,
        logComponentVerbosity: {tlaPlusTrace: 1}
    })
"""

import datetime
import re
from dataclasses import dataclass

from bson import json_util  # pip install pymongo

from system_state import OplogEntry

# Match lines like:
# 2019-07-16T12:24:41.964-0400 I  TLA_PLUS_TRACE [replexec-0]
#   {"action": "BecomePrimaryByMagic", ...}
line_pat = re.compile(
    r'(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}[+-]\d{4})'
    r'.+?TLA_PLUS_TRACE.+? '
    r'(?P<json>{.*})')


@dataclass
class LogEvent:
    timestamp: datetime.datetime
    action: str
    server_id: int
    term: int
    server_state: str
    commit_point: OplogEntry
    log: tuple


def parse_log(logfile_stream, port_mapper, oplog_index_mapper):
    """Yield (timestamp, SystemState) pairs for heartbeat response events."""
    for line in logfile_stream:
        try:
            match = line_pat.match(line)
            if match:
                timestamp = datetime.datetime.strptime(
                    match.group('timestamp'), '%Y-%m-%dT%H:%M:%S.%f%z')

                # json_util converts e.g. $numberLong to Python int.
                obj = json_util.loads(match.group('json'))
                # MongoDB terms start at -1.
                # TODO: Is this right?
                term = max(obj['commitPoint']['t'], 0)
                commit_point = OplogEntry(
                    term=term,
                    index=oplog_index_mapper.get_index(obj['commitPoint']['ts'])
                )

                assert obj['serverState'] in ('PRIMARY', 'SECONDARY')
                server_state = (
                    'Leader' if obj['serverState'] == 'PRIMARY' else 'Follower')

                yield LogEvent(
                    timestamp=timestamp,
                    action=obj['action'],
                    server_id=port_mapper.get_server_id(obj['myPort']),
                    term=obj['term'],
                    server_state=server_state,
                    commit_point=commit_point,
                    # TODO
                    log=())
        except Exception:
            print('Exception parsing line: {!r}'.format(line))
            raise

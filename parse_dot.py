"""
Parse GraphViz dot file, exported from the TLC model-checker with
'-dump dot,colorize,actionactions'.
"""

import logging
import os
import re
import time

import parse_tla


class StateGraph:

    def __init__(self):
        # Map: source state id -> action name -> destination state ids.
        # Should be a defaultdict of defaultdicts, but it wouldn't be picklable.
        self._transitions = {}
        self._state_to_id = {}
        self._id_to_state = {}
        self._init_state = None
        self._max_log_len = 0

    def __str__(self):
        return (
            f'{self.__class__.__name__}: {len(self._state_to_id)} states,'
            f' {len(self._transitions)} transitions, max oplog length'
            f' {self._max_log_len}'
        )

    def set_init_state(self, state, state_id):
        assert self._init_state is None
        self._init_state = state
        self.add_state(state, state_id)

    def get_init_state(self):
        assert self._init_state is not None
        return self._init_state

    def add_state(self, state, state_id):
        assert state not in self._state_to_id
        assert state_id not in self._id_to_state
        self._state_to_id[state] = state_id
        self._id_to_state[state_id] = state
        self._max_log_len = max(self._max_log_len,
                                *(len(log) for log in state.log))

    def add_transition(self, action, from_id, to_id):
        action_to_id = self._transitions.setdefault(from_id, {})
        action_to_id.setdefault(action, set()).add(to_id)

    def next_actions(self, state):
        from_id = self._state_to_id[state]
        if from_id not in self._transitions:
            return set()
        return self._transitions[from_id].keys()

    def next_states(self, state, action):
        from_id = self._state_to_id[state]
        to_ids = self._transitions[from_id].get(action, set())
        return [self._id_to_state[to_id] for to_id in to_ids]

    def get_state_id(self, state):
        return self._state_to_id[state]


# Like: 123 [action="... bunch of TLA+ ...",style = filled]
node_pat = re.compile(r'(?P<id>-?\d+)\s+\[label="(?P<tla>.+)".*];?')

# Like: 123 -> -248 [label="BecomePrimaryByMagic",color="2",fontcolor="2"];
# TODO: test without -dump colorize
edge_pat = re.compile(
    r'(?P<from>-?\d+)\s+->\s+(?P<to>-?\d+)\s+'
    r'\[label="(?P<action>.+?)"(,|).*];?')


def parse_dot(dotfile_stream):
    size = os.path.getsize(dotfile_stream.name)
    parsed_bytes = 0
    last_log_time = time.time()
    graph = StateGraph()
    found_init_state = False
    for line in dotfile_stream:
        parsed_bytes += len(line)
        # Log every 10 seconds.
        now = time.time()
        if now > last_log_time + 10:
            progress_pct = (100 * parsed_bytes) // size
            logging.info(f'Parsing graph... {progress_pct:3}%')
            last_log_time = now

        try:
            match = node_pat.match(line)
            if match:
                tla_encoded = match.group('tla')
                state_id = int(match.group('id'))
                # tla_encoded is backslash-escaped like "/\\ x = 0\n".
                tla = tla_encoded.encode('ascii').decode('unicode_escape')
                state = parse_tla.parse_tla(tla)
                if not found_init_state:
                    graph.set_init_state(state, state_id)
                    found_init_state = True
                else:
                    graph.add_state(state, state_id)
                continue

            match = edge_pat.match(line)
            if match:
                graph.add_transition(
                    match.group('action'),
                    int(match.group('from')),
                    int(match.group('to')))

                continue

            # print('Unmatched line: {!r}'.format(line))
        except Exception:
            print('Exception parsing line: {!r}'.format(line))
            raise

    return graph

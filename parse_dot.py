"""
Parse GraphViz dot file, exported from the TLC model-checker with
'-dump dot,colorize,actionactions'.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict

import parse_tla
from system_state import SystemState


@dataclass
class StateGraph:
    state_to_id: Dict[SystemState, int] = field(default_factory=dict)
    # This should be a defaultdict but then its default_factory would be a
    # lambda, and the class would not be picklable.
    transitions: Dict[int, Dict[str, set]] = field(default_factory=dict)
    """Map: source state id -> action name -> destination state ids"""

    def __post_init__(self):
        # Just an implementation detail, not a real data field.
        self.id_to_state = {}
        self.init_state = None

    def add_state(self, state, state_id):
        assert state not in self.state_to_id
        assert state_id not in self.id_to_state
        self.state_to_id[state] = state_id
        self.id_to_state[state_id] = state

    def add_transition(self, action, from_id, to_id):
        action_to_id = self.transitions.setdefault(from_id, {})
        action_to_id.setdefault(action, set()).add(to_id)

    def next_actions(self, state):
        from_id = self.state_to_id[state]
        if from_id not in self.transitions:
            return set()
        return self.transitions[from_id].keys()

    def next_states(self, state, action):
        from_id = self.state_to_id[state]
        to_ids = self.transitions[from_id].get(action, set())
        return [self.id_to_state[to_id] for to_id in to_ids]


# Like: 123 [action="... bunch of TLA+ ...",style = filled]
node_pat = re.compile(r'(?P<id>-?\d+)\s+\[label="(?P<tla>.+)".*];?')

# Like: 123 -> -248 [label="BecomePrimaryByMagic",color="2",fontcolor="2"];
# TODO: test without -dump colorize
edge_pat = re.compile(
    r'(?P<from>-?\d+)\s+->\s+(?P<to>-?\d+)\s+'
    r'\[label="(?P<action>.+?)"(,|).*];?')


def parse_dot(dotfile_stream):
    graph = StateGraph()
    line_no = 0
    for line in dotfile_stream:
        line_no += 1
        if line_no % 10000 == 0:
            logging.info(f'Parsing line {line_no}')

        try:
            match = node_pat.match(line)
            if match:
                tla_encoded = match.group('tla')
                state_id = int(match.group('id'))
                # tla_encoded is backslash-escaped like "/\\ x = 0\n".
                tla = tla_encoded.encode('ascii').decode('unicode_escape')
                state = parse_tla.parse_tla(tla)
                graph.add_state(state, state_id)
                if graph.init_state is None:
                    graph.init_state = state

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

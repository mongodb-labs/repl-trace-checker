import argparse
import logging
import os
import pickle
import sys
from os.path import getmtime

import parse_dot
import parse_log
from system_state import OplogIndexMapper, PortMapper, SystemState

logging.basicConfig(
    format='%(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true',
                        help='Re-parse dotfile')
    parser.add_argument('dotfile', type=argparse.FileType('r'))
    parser.add_argument('logfile', type=argparse.FileType('r'), nargs='+')
    return parser.parse_args()


def load_graph(args):
    cache_file_name = 'state_graph.pickle'
    if (not args.refresh
            and os.path.exists(cache_file_name)
            and getmtime(cache_file_name) > getmtime(args.dotfile.name)):
        logging.info(f"Loading cached {cache_file_name}")
        graph = pickle.load(open(cache_file_name, 'rb'))
    else:
        logging.info(f"Loading {args.dotfile.name}")
        graph = parse_dot.parse_dot(args.dotfile)
        logging.info("Caching graph")
        with open('state_graph.pickle', 'wb') as f:
            pickle.dump(graph, f)

    logging.info(f"Loaded {graph}")
    return graph


def update_state(current_state, log_event):
    # log is a tuple like (server 1's log, server 2's log, server 3's log),
    # same for server_state and commit_point.
    next_log = list(current_state.log)
    next_log[log_event.server_id] = log_event.log

    next_server_state = list(current_state.server_state)
    next_server_state[log_event.server_id] = log_event.server_state

    next_commit_point = list(current_state.commit_point)
    next_commit_point[log_event.server_id] = log_event.commit_point

    return SystemState(
        n_servers=current_state.n_servers,
        global_current_term=log_event.term,
        log=tuple(next_log),
        server_state=tuple(next_server_state),
        commit_point=tuple(next_commit_point))


def main(args):
    graph = load_graph(args)
    current_state = graph.get_init_state()
    if len(args.logfile) != current_state.n_servers:
        logging.error(
            f"Graph's initial state has {current_state.n_servers} servers,"
            f" but you provided {len(args.logfile)} mongod logs")
        sys.exit(1)

    port_mapper = PortMapper()
    oplog_index_mapper = OplogIndexMapper()
    for i, log_line in enumerate(parse_log.merge_log_streams(args.logfile)):
        log_event = parse_log.parse_log_line(
            log_line, port_mapper, oplog_index_mapper)
        state_id = graph.get_state_id(current_state)
        if i == 0:
            logging.info('Initial state')
        logging.info(f'State id {state_id}:\n{current_state.pretty()}')
        logging.info(f'Log line:\n{log_event.pretty()}')
        next_state = update_state(current_state, log_event)
        next_actions = graph.next_actions(current_state)
        if not next_actions:
            logging.error(f"No allowed next actions after state id {state_id}!")
            sys.exit(1)

        if log_event.action not in next_actions:
            logging.error(f"Next action not in allowed next actions:"
                          f" {', '.join(next_actions)}")
            sys.exit(1)

        allowed_states = graph.next_states(current_state, log_event.action)

        if not allowed_states:
            logging.error(f"Next state:\n{next_state.pretty()}")
            logging.error(f"No allowed next states after state id {state_id}!")
            sys.exit(1)
        elif next_state not in allowed_states:
            logging.error("Next state not in allowed next states")
            logging.error(f"Next state:\n{next_state.pretty()}")
            for i, state in enumerate(allowed_states):
                logging.error(f" -- Allowed state {i} -- \n{state.pretty()}")

            sys.exit(1)

        current_state = next_state


if __name__ == '__main__':
    main(parse_args())

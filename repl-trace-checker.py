import argparse
import heapq
import logging
import os
import pickle
import sys
from os.path import getmtime

import parse_dot
import parse_log
from system_state import PortMapper, SystemState, OplogIndexMapper

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
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
        logging.info("Done loading")
        return graph

    logging.info(f"Parsing {args.dotfile.name}")
    graph = parse_dot.parse_dot(args.dotfile)
    logging.info("Caching graph")
    with open('state_graph.pickle', 'wb') as f:
        pickle.dump(graph, f)

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
    current_state = graph.init_state
    port_mapper = PortMapper()
    oplog_index_mapper = OplogIndexMapper()
    logfile_streams = (
        parse_log.parse_log(logfile_stream, port_mapper, oplog_index_mapper)
        for logfile_stream in args.logfile)

    # Merge logs, sorting by timestamp.
    log_events = heapq.merge(
        *logfile_streams, key=lambda event: event.timestamp)

    for log_event in log_events:
        logging.info(current_state)
        logging.info(log_event)
        next_state = update_state(current_state, log_event)
        try:
            allowed_states = graph.next_states(current_state, log_event.action)
        except KeyError:
            actions = graph.next_actions(current_state)
            if actions:
                logging.error(
                    f"No {log_event.action} action from current state")
                logging.error("Enabled actions:")
                for action in actions:
                    logging.error(action)
            else:
                logging.error("No actions enabled from current state")
            sys.exit(1)

        if not allowed_states:
            logging.error(f"Next state: {next_state}")
            logging.error("No allowed next states!")
            sys.exit(1)
        elif next_state not in allowed_states:
            logging.error("Next state not in allowed next states")
            logging.error("Next state:")
            logging.error(next_state)
            logging.error("Allowed states:")
            for state in allowed_states:
                logging.error(state)

            sys.exit(1)

        current_state = next_state


if __name__ == '__main__':
    main(parse_args())

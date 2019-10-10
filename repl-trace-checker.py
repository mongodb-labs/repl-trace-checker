import argparse
import logging
import os
from contextlib import contextmanager
from tempfile import NamedTemporaryFile

import parse_log
from repl_checker_dataclass import jinja2_template_from_string
from system_state import OplogIndexMapper, PortMapper, SystemState

this_dir = os.path.realpath(os.path.dirname(__file__))

logging.basicConfig(
    format='%(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check that mongod logs match a TLA+ spec")

    parser.add_argument(
        'logfile',
        type=argparse.FileType('r'),
        nargs='+',
        help='One or more mongod log files')

    # Unlike argparse.FileType, this checks the file exists, but returns its
    # path instead of a read handle.
    def is_file(arg):
        try:
            with open(arg, 'r'):
                return arg
        except IOError:
            raise argparse.ArgumentError("Could not open file")

    parser.add_argument(
        'specfile',
        type=is_file,
        help='TLA+ spec to check against')

    parser.add_argument(
        '--outfile',
        help='Optional location to save temporary generated spec for debugging')

    return parser.parse_args()


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


@contextmanager
def temp_or_permanent_file_path(filename=None):
    """Create a context for writing to a file.

    If filename is None, create a temporary file that is deleted when the
    context block closes.
    """
    if filename is not None:
        f = open(filename, 'w+')
        yield f
        f.close()
    else:
        with NamedTemporaryFile(mode='w+', suffix='.tla') as f:
            yield f


def main(args):
    trace = []
    port_mapper = PortMapper()
    oplog_index_mapper = OplogIndexMapper()

    # TODO: How to get the initial state from the spec? Can TLC help?
    n_servers = len(args.logfile)
    current_state = SystemState(
        n_servers=n_servers,
        global_current_term=0,
        log=((),) * n_servers,
        server_state=("Follower",) * n_servers,
        commit_point=({'term': 0, 'index': 0},) * n_servers)

    for i, log_line in enumerate(parse_log.merge_log_streams(args.logfile)):
        log_event = parse_log.parse_log_line(
            log_line, port_mapper, oplog_index_mapper)
        logging.info(f'Current state:\n{current_state.pretty()}')
        logging.info(f'Log line:\n{log_event.pretty()}')
        trace.append(current_state)

        # Generate next state.
        current_state = update_state(current_state, log_event)

    template = jinja2_template_from_string(
        open(os.path.join(this_dir, 'trace.tla.jinja2')).read())

    tla_out = template.render(
        system_state_fields=SystemState.tla_variable_names())

    # Creates a temporary file if args.outfile is None.
    with temp_or_permanent_file_path(args.outfile) as outfile:
        outfile.write(tla_out)
        outfile.flush()
        print(outfile.name)


if __name__ == '__main__':
    main(parse_args())

import argparse
import logging
import os
import requests
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from tqdm import tqdm

import parse_log
from repl_checker_dataclass import jinja2_template_from_string
from system_state import CommitPoint, PortMapper, ServerState, SystemState

this_dir = os.path.realpath(os.path.dirname(__file__))


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
        except OSError as e:
            raise argparse.ArgumentTypeError(e)

    parser.add_argument(
        'specfile',
        type=is_file,
        help='TLA+ spec to check against')

    parser.add_argument(
        '--keep-temp-spec',
        action='store_true',
        help='Save generated spec, as file "Trace.tla"')

    parser.add_argument(
        '--tla2tools-jar',
        help='Path to tla2tools.jar (otherwise it will be downloaded)')

    parser.add_argument(
        '--heap-size-gb',
        type=int,
        help='Java heap size for TLC, in gigabytes')

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help="Don't log each parsed action (runs much faster)")

    return parser.parse_args()


def update_state(current_state, log_event):
    # current_state.log is a tuple like:
    #
    #    (server 1's oplog, server 2's oplog, server 3's oplog)
    #
    # Same for current_state.state and current_state.commitPoint. Update the
    # value in each of these tuples for log_event's server.
    _default = object()

    def update(variable_name, other_nodes=_default):
        """In a list of values per server, replace the value for one server."""
        if other_nodes == _default:
            next_values = list(getattr(current_state, variable_name))
        else:
            next_values = [other_nodes] * current_state.n_servers

        next_values[log_event.server_id] = getattr(log_event, variable_name)
        return tuple(next_values)

    new_log = update('log')
    new_commit = log_event.commitPoint
    if new_commit.is_null():
        committed = current_state.committedEntries.copy()
    else:
        # The LearnCommitPointWithTermCheck action allows a node to learn a
        # commit point past its current oplog, so find the new commit point's
        # index by reading the longest oplog.
        longest_log = max(new_log, key=lambda log: len(log))
        committed_entry = longest_log[new_commit.index - 1]
        assert committed_entry.term == new_commit.term, \
            (f"Server {log_event.server_id} oplog entry at 1-based index"
             f" {new_commit.index} has term {committed_entry.term}, commit"
             f" point term is {new_commit.term}")

        # Add prefix-committed entries to set of committed entries.
        committed = current_state.committedEntries | {
            CommitPoint(term=entry.term, index=entry.index)
            for entry in committed_entry.get_complete_log()
        }

    if log_event.action == 'BecomePrimaryByMagic':
        # In RaftMongo.tla voters update their terms and step down instantly.
        currentTerm = update('currentTerm', other_nodes=log_event.currentTerm)
        state = update('state', other_nodes=ServerState.Follower)
    else:
        currentTerm = update('currentTerm')
        state = update('state')

    return SystemState(
        n_servers=current_state.n_servers,
        committedEntries=committed,
        currentTerm=currentTerm,
        action=log_event.action,
        log=new_log,
        state=state,
        commitPoint=update('commitPoint'),
        serverLogLocation=log_event.location)


class TLCInputs:
    def __init__(self, permanent):
        """Create TLC's input TLA+ specification and configuration.

        If permanent is False, create temporary files that are deleted when the
        context block closes. Otherwise create permanent files in the working
        dir.
        """
        self.permanent = permanent
        self.dir_path = None
        self.spec = None
        self.config = None
        self._tmp_dir = None

    def __enter__(self):
        spec_filename = 'Trace.tla'
        cfg_filename = 'Trace.cfg'
        mode = 'w+'

        if self.permanent:
            self.dir_path = os.getcwd()
            self.spec = open(spec_filename, mode)
            self.config = open(cfg_filename, mode)
        else:
            self._tmp_dir = TemporaryDirectory()
            self.dir_path = self._tmp_dir.name
            spec_path = os.path.join(self._tmp_dir.name, spec_filename)
            cfg_path = os.path.join(self._tmp_dir.name, cfg_filename)
            self.spec = open(spec_path, mode)
            self.config = open(cfg_path, mode)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.spec.close()
        self.config.close()
        if self._tmp_dir:
            self._tmp_dir.cleanup()


def run_tlc(tla2tools_jar, heap_size_gb):
    tla_install_dir = os.path.join(this_dir, 'tla-bin')
    os.makedirs(tla_install_dir, exist_ok=True)
    tools_install = os.path.join(tla_install_dir, 'tla2tools.jar')

    def run_java(cmd):
        opts = ['-XX:+UseParallelGC']
        if heap_size_gb is not None:
            opts.append(f'-Xmx{heap_size_gb}g')

        java_cmd = ['java'] + opts + ['-cp', f'{tla_install_dir}/*'] + cmd
        logging.debug(' '.join(java_cmd))
        subprocess.check_call(java_cmd, cwd=this_dir)

    if tla2tools_jar:
        shutil.copy(tla2tools_jar, tools_install)
    else:
        # Releases are at tla.msr-inria.inria.fr/tlatoolbox/dist/tla2tools.jar
        # but we want nightlies.
        r = requests.get('https://nightly.tlapl.us/dist/tla2tools.jar',
                         stream=True)

        with open(tools_install, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)

    # Log start / end so we can calculate duration from log timestamps.
    logging.info('Starting TLC')
    run_java(['tlc2.TLC', 'Trace.tla'])
    logging.info('Finished TLC')


def main(args):
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=logging.INFO if args.quiet else logging.DEBUG,
        datefmt='%Y-%m-%d %H:%M:%S')

    logging.info('Reading logs')
    merged_logs = list(parse_log.merge_log_streams(args.logfile))
    servers = set(log_line.obj['host'] for log_line in merged_logs)
    logging.info(f"{len(merged_logs)} TLA+ trace events")
    logging.info(f"Servers: {' '.join(servers)}")

    # TODO: How to get the initial state from the spec? Can TLC help?
    n_servers = len(servers)
    current_state = SystemState(
        n_servers=n_servers,
        committedEntries=set(),
        currentTerm=(0,) * n_servers,
        action='Init',
        log=((),) * n_servers,
        state=(ServerState.Follower,) * n_servers,
        commitPoint=({'term': 0, 'index': 0},) * n_servers,
        serverLogLocation="")

    # Track the max number of oplog entries added in one event.
    max_client_write_size = 0
    trace = []
    port_mapper = PortMapper()
    oplog_index_mapper = parse_log.OplogIndexMapper()

    logging.info('Generating states')
    # If quiet, just show progress bar with tqdm.
    disable_tqdm = True if not args.quiet else None
    for i, log_line in enumerate(tqdm(merged_logs, disable=disable_tqdm),
                                 start=1):
        try:
            log_event = parse_log.parse_log_line(
                log_line, port_mapper, oplog_index_mapper)
        except Exception:
            logging.exception("Parsing log")
            break

        if not args.quiet:
            logging.info(
                f'{"Initial" if i == 1 else "Current"} state:'
                f'\n{current_state.pretty()}')
            logging.info(f'Log line #{i}/{len(merged_logs)}:'
                         f'\n{log_event.pretty()}')

        trace.append(current_state)

        # Generate next state.
        max_oplog_len = current_state.max_oplog_len
        current_state = update_state(current_state, log_event)
        max_client_write_size = max(max_client_write_size,
                                    current_state.max_oplog_len - max_oplog_len)

    if not args.quiet:
        logging.info(f'Final state:\n{current_state.pretty()}')

    tla_template = jinja2_template_from_string(
        open(os.path.join(this_dir, 'Trace.tla.jinja2')).read())

    tla_out = tla_template.render(
        raft_mongo_variables=SystemState.raft_mongo_variables(),
        all_tla_variables=SystemState.all_tla_variables(),
        max_client_write_size=max_client_write_size,
        n_servers=current_state.n_servers,
        trace=trace)

    cfg_template = jinja2_template_from_string(
        open(os.path.join(this_dir, 'Trace.cfg.jinja2')).read())

    cfg_out = cfg_template.render()

    # Creates temporary files if args.keep_temp_spec is False.
    with TLCInputs(args.keep_temp_spec) as inputs:
        logging.info(f'Generating {inputs.spec.name}')
        inputs.spec.write(tla_out)
        inputs.spec.flush()

        inputs.config.write(cfg_out)
        inputs.config.flush()

        try:
            shutil.copy(args.specfile, inputs.dir_path)
            if args.keep_temp_spec:
                logging.info(f'Copied {args.specfile} to {inputs.dir_path}')

        except shutil.SameFileError:
            # --keep-temp-spec with a spec file in the current directory.
            pass

        try:
            run_tlc(tla2tools_jar=args.tla2tools_jar,
                    heap_size_gb=args.heap_size_gb)
            return 0
        except subprocess.SubprocessError as exc:
            logging.error(exc)
            return exc.returncode


if __name__ == '__main__':
    sys.exit(main(parse_args()))

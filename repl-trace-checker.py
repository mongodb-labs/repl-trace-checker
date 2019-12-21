import argparse
import logging
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import parse_log
from repl_checker_dataclass import jinja2_template_from_string
from system_state import PortMapper, ServerState, SystemState

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

    return parser.parse_args()


def update_state(current_state, log_event):
    # current_state.log is a tuple like:
    #
    #    (server 1's oplog, server 2's oplog, server 3's oplog)
    #
    # Same for state, currentTerm, and commitPoint. Update the value in each of
    # these tuples for log_event's server.

    def update(variable_name):
        """In a list of values per server, replace the value for one server."""
        next_values = list(getattr(current_state, variable_name))
        next_values[log_event.server_id] = getattr(log_event, variable_name)
        return tuple(next_values)

    return SystemState(
        n_servers=current_state.n_servers,
        action=log_event.action,
        log=update('log'),
        state=update('state'),
        currentTerm=update('currentTerm'),
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


def run_tlc(dir_path):
    tla_bin_dir = os.path.join(this_dir, 'tla-bin')
    tla_install_dir = os.path.join(this_dir, '.tla-bin-install')
    download = os.path.join(tla_bin_dir, 'download_or_update_tla.sh')
    install = os.path.join(tla_bin_dir, 'install.sh')

    if not os.path.exists(os.path.join(this_dir, download)):
        raise Exception("Must 'git submodule init' to install tla-bin")

    def run(cmd, cwd):
        subprocess.check_call(cmd, cwd=cwd)

    run([download], cwd=tla_bin_dir)
    run([install, tla_install_dir], cwd=tla_bin_dir)

    tlc = os.path.join(tla_install_dir, 'bin/tlc')
    trace_tla = os.path.join(dir_path, 'Trace.tla')
    run([tlc, trace_tla], cwd=this_dir)


def main(args):
    merged_logs = list(parse_log.merge_log_streams(args.logfile))
    servers = set(log_line.obj['host'] for log_line in merged_logs)
    logging.info(f'Servers: {servers}')

    # TODO: How to get the initial state from the spec? Can TLC help?
    n_servers = len(servers)
    current_state = SystemState(
        n_servers=n_servers,
        action='Init',
        log=((),) * n_servers,
        state=(ServerState.Follower,) * n_servers,
        currentTerm=(0,) * n_servers,
        commitPoint=({'term': 0, 'index': 0},) * n_servers,
        serverLogLocation="")

    # Track the max number of oplog entries added in one event.
    max_client_write_size = 0
    trace = []
    port_mapper = PortMapper()
    oplog_index_mapper = parse_log.OplogIndexMapper()

    for i, log_line in enumerate(merged_logs, start=1):
        log_event = parse_log.parse_log_line(
            log_line, port_mapper, oplog_index_mapper)
        logging.info(
            f'{"Initial" if i == 1 else "Current"} state:\n{current_state.pretty()}')
        logging.info(f'Log line #{i}:\n{log_event.pretty()}')
        trace.append(current_state)

        # Generate next state.
        max_oplog_len = current_state.max_oplog_len
        current_state = update_state(current_state, log_event)
        max_client_write_size = max(max_client_write_size,
                                    current_state.max_oplog_len - max_oplog_len)

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
        print(f'Generating {inputs.spec.name}')
        inputs.spec.write(tla_out)
        inputs.spec.flush()

        inputs.config.write(cfg_out)
        inputs.config.flush()

        try:
            shutil.copy(args.specfile, inputs.dir_path)
            if args.keep_temp_spec:
                print(f'Copied {args.specfile} to {inputs.dir_path}')

        except shutil.SameFileError:
            # --keep-temp-spec with a spec file in the current directory.
            pass

        try:
            run_tlc(inputs.dir_path)
            return 0
        except subprocess.SubprocessError as exc:
            print(exc)
            return exc.returncode


if __name__ == '__main__':
    sys.exit(main(parse_args()))

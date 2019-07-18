# Parsing code copied from https://github.com/visualzhou/tla-trace-formatter
from lark import Lark

from system_state import SystemState, OplogEntry

with open('output-grammar.lark', 'r') as grammar:
    parser = Lark(grammar, start='state', propagate_positions=True)


def parse_tla(text):
    tree = parser.parse(text)
    kvs = {str(kv.children[0]): kv.children[1] for kv in tree.children}
    server_state = parse_state(kvs['state'])
    n_servers = len(server_state)
    return SystemState(
        n_servers=n_servers,
        global_current_term=parse_term(kvs['globalCurrentTerm']),
        log=parse_log(kvs['log']),
        server_state=server_state,
        commit_point=parse_commit_point(kvs['commitPoint']))


def parse_term(data):
    return int(data.children[0].children[0])


def parse_log(data):
    def gen_logs():
        for log in data.children[0].children:
            yield log.children[1].children[0].children

    def gen_entries(log):
        index = 0
        # A sequence like <<[term |-> 1], [term |-> 2]>>
        for entry in log:
            if entry in ('<<', '>>'):
                continue

            # kv is like "term -> 1"
            kv = entry.children[0].children[0]
            term = int(kv.children[1].children[0].children[0])
            yield OplogEntry(term=term, index=index)
            index += 1

    tmp = tuple(tuple(gen_entries(log)) for log in gen_logs())
    return tmp


def parse_state(data):
    def gen():
        for c in data.children[0].children:
            yield str(c.children[1].children[0].children[0])

    return tuple(gen())


def parse_commit_point(data):
    def gen():
        for commit_point in data.children[0].children:
            index_and_term = commit_point.children[1].children[0]
            index = int(
                index_and_term.children[0].children[1].children[0].children[0])

            term = int(
                index_and_term.children[1].children[1].children[0].children[0])

            yield OplogEntry(term=term, index=index)

    return tuple(gen())

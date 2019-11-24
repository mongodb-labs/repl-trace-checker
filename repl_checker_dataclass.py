import dataclasses
import itertools
import textwrap

from jinja2 import Environment


def pretty_oplog(oplog):
    """Summarize an oplog for diagnostic output.

    oplog is a tuple like ({'term': 1}, {'term': 2}, ...).
    """

    def get_term(entry):
        return entry['term']

    def gen():
        index = 0
        for term, entries in itertools.groupby(oplog, key=get_term):
            num_entries = len(list(entries))
            if num_entries == 1:
                yield (f'term {term} entry {index}')
            else:
                yield (f'term {term} entries {index}-{index + num_entries - 1}')

            index += num_entries

    return f'[{", ".join(gen())}]'


_environment = Environment(lstrip_blocks=True, trim_blocks=True)
_environment.filters['oplog'] = pretty_oplog


def jinja2_template_from_string(s):
    return _environment.from_string(s)


def repl_checker_dataclass(_cls=None, **kwargs):
    def wrap(cls):
        wrapped = dataclasses.dataclass(cls, **kwargs)

        if hasattr(wrapped, '__pretty_template__'):
            template = jinja2_template_from_string(wrapped.__pretty_template__)

            def pretty(self):
                return textwrap.indent(
                    template.render(dataclasses.asdict(self)),
                    '  ')

        else:
            def pretty(self):
                field_len = max(len(f.name) for f in dataclasses.fields(self))
                attrs = '\n'.join(
                    f"{name + ':':{field_len + 1}} {value}" for name, value in
                    dataclasses.asdict(self).items())

                return f'{cls.__name__}\n{attrs}'

        wrapped.pretty = pretty
        return wrapped

    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called without parens.
    return wrap(_cls)

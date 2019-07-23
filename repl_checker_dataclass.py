import dataclasses
import textwrap

from jinja2 import Environment, Template

environment = Environment()


def oplogentry_filter(value):
    return f'[{value["term"]}, {value["index"]}]'


environment.filters['oplogentry'] = oplogentry_filter


def repl_checker_dataclass(_cls=None, **kwargs):
    def wrap(cls):
        wrapped = dataclasses.dataclass(cls, **kwargs)

        if hasattr(wrapped, '__pretty_template__'):
            template = environment.from_string(wrapped.__pretty_template__)

            def pretty(self):
                return textwrap.indent(template.render(
                    dataclasses.asdict(self), trim_blocks=True,
                    lstrip_blocks=True), '  ')

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

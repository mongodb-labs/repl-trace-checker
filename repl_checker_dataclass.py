import dataclasses


def repl_checker_dataclass(_cls=None, **kwargs):
    def wrap(cls):
        wrapped = dataclasses.dataclass(cls, **kwargs)

        def pretty(self):
            field_len = max(len(f.name) for f in dataclasses.fields(self))
            attrs = '\n'.join(f"{name + ':':{field_len + 1}} {value}" for name, value in
                              dataclasses.asdict(self).items())

            return f'{cls.__name__}\n{attrs}'

        wrapped.pretty = pretty
        return wrapped

    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called without parens.
    return wrap(_cls)

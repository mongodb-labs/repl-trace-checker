# MongoDB Replication Protocol Trace Checker

Compare a sequence of messages from an actual MongoDB replica set with
[Siyuan Zhou's TLA+ spec of MongoDB replication](https://github.com/visualzhou/mongo-repl-tla)
to check whether the actual replica set's steps are permitted by the spec.

## Implementation notes

Tried pydot but it can't parse TLC's outputs (which seems likely a pydot bug).

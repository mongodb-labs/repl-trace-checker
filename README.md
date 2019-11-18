# MongoDB Replication Protocol Trace Checker

Compare a sequence of messages from an actual MongoDB replica set with
[Siyuan Zhou's TLA+ spec of MongoDB replication](https://github.com/visualzhou/mongo-repl-tla)
to check whether the actual replica set's steps are permitted by the spec.

## Background

TLA+ is a mathematical language for specifying distributed systems algorithms.
A TLA+ spec can be checked with TLC, a tool that verifies that any sequence of
steps the algorithm can perform will obey the spec's invariants. However,
checking that a TLA+ spec is correct does not guarantee that the spec matches
your actual program. One solution is model-based trace-checking[1]: check that
actual executions of your program, e.g. during integration tests, each match
some sequence of steps permitted by the spec. We implement a model-based
trace-checking technique specific to TLA+ described by [2]. 

[1]. Howard, Yvonne & Gruner, Stefan & Gravell, A & Ferreira, Carla & Augusto
Wrede, Juan. (2011). Model-Based Trace-Checking.

[2]. Pressler, Ron. (2018).  Verifying Software Traces Against a Formal 
Specification with TLA+ and TLC.

## This project

I want to check that an actual MongoDB replica set's series of state changes
correspond to a sequence of steps in Siyuan Zhou's TLA+ spec, `RaftMongo.tla`.

First I build mongod with extra tracing. Each time the server executes a step
that is equivalent to one of the `RaftMongo.tla` actions (AppendOplog,
RollbackOplog, BecomePrimaryByMagic, or ClientWrite), it logs the actual values
of all variables that are modeled by the spec. I start a replica set, perform
some writes, and stop the set.

Next, I run a Python script reads all the replica set members' logs and
constructs an execution trace, as follows. The script begins with the spec's
initial state. (TODO: In fact the initial state is hardcoded in Python.)
Then, for each log message from the replica set, the script
creates the next state, which includes the changes expressed by the log
message. For example, if Server 1 becomes primary, it logs that its role is now
"Leader". The script makes the next state, which is the same as the previous
except for Server 1's new role.

Once the script has created the trace, it follows the technique described in
[2]. It formats the trace as a TLA+ tuple of tuples of variable values, and
creates a new TLA+ spec to check that this trace is permitted by
`RaftMongo.tla`. 

## Instructions

**Run a replica set**

* Clone [my "repl-trace-checker" MongoDB branch](https://github.com/ajdavis/mongo/tree/repl-trace-checker)
* Build `mongod` and `mongo`
* Run the script included at the top directory on my branch:
```
./mongo --nodb sample-tla-plus-trace-replica-set.js
```

**Run the checker**

* Clone this repository
* With Python 3.6 or later:
```
python -m pip install -r requirements.txt
python repl-trace-checker.py <LOG1> <LOG2> ...
```
* Replace LOG1, LOG2, etc. with the `mongod.log` file of each replica.

The script parses the mongod log files and generates a TLA+ spec which checks
that the trace represented by the log files is permitted by `RaftMongo.tla`.

## Current status

I have not yet added logging in the server implementations of the commit point
learning protocol. Therefore the server's execution trace appears wrong: between 
one AppendOplog action and the next, for example, its commit point advances, but 
it never logs the AdvanceCommitPoint or similar action. The trace checker 
considers this an error, as expected.

[Sample output from the trace checker](./sample-output.txt).

## Next Steps

* Add logging to the server implementations of the TLA+ actions 
  AdvanceCommitPoint, LearnCommitPointWithTermCheckAction, and 
  LearnCommitPointFromSyncSourceNeverBeyondLastAppliedAction. 
* Trigger a rollback and check its trace.
* Introduce a bug in the actual replica set, traces should fail the checker.
* Prevent oplog truncation while the actual replica set is running.
* Note the trick for debugging traces: Add "Trace[i]" in the Toolbox's
  "Error-Trace Exploration" box

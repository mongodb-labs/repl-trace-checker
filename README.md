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

First I run mongod with extra tracing. Each time the server executes a step
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

* Build the most recent version of `mongod` and `mongo`.
* Run the script included in this repository.
```
./mongo --nodb sample-replica-set.js
```

**Run the checker**

* Clone this repository
* With Python 3.6 or later:

```
python -m pip install -r requirements.txt
python repl-trace-checker.py <LOG1> <LOG2> ... <SPEC>
```
* Replace LOG1, LOG2, etc. with the `mongod.log` file of each replica.
* Replace SPEC with the path to RaftMongo.tla.

The script parses the mongod log files and generates a TLA+ spec which checks
that the trace represented by the log files is permitted by `RaftMongo.tla`.
The script installs or updates the TLA+ tools and runs the model checker program
TLC on the generated spec.

Caveats:
* If a mongod's log is split across several files, they must be merged in
  chronological order into one file.
* The replica set must never be single-node (because single-node sets handle
  the commitPoint differently from the RaftMongo.tla spec). You must disable
  replsettest.js's default behavior of initializing a set with one node and then
  adding the remainder of the nodes, see SERVER-45228.
* Auth is not supported (it writes system.keys entries that are 
  majority-committed during initial sync as the replica set is initialized,
  which violates RaftMongo.tla).

**Debug**

When the script finds a violation of the spec it logs something unhelpful like:

```
Error: Action property line 274, col 19 to line 274, col 31 of module RaftMongo is violated.
```

You can use the [TLA+ Toolbox](https://github.com/tlaplus/tlaplus/releases) IDE 
to debug it.

* Run `repl-trace-checker.py --keep-temp-spec`.
* Open the generated Trace.tla in the TLA+ Toolbox.
* Choose "TLC Model Checker" -> "New Model".
* Under "What is the behavior spec?" choose "Temporal formula" and enter 
  "TraceBehavior".
* Under "Properties" click "Add" and enter "Safety".
![Model Overview](https://raw.githubusercontent.com/ajdavis/repl-trace-checker/master/readme-images/model-overview.png)
* Choose "TLC Model Checker" -> "Run Model". You should see a violation error
and an error trace.
* In "Error-Trace Exploration" click "Add" and enter `Trace[i]`. Click 
  "Explore".
* More information will be added to the error trace, including the spec action
  the server thought it took at each step, and the MongoDB server log line that
  generated each step.  
![Error Trace](https://raw.githubusercontent.com/ajdavis/repl-trace-checker/master/readme-images/error-trace.png)

## Current status

Trace logging is implemented in mongod as of commit f515d2ad on MongoDB's master 
branch. The RaftMongo.tla spec requires small updates to match the trace; these
are in progress. 

[Sample output from the trace checker](./sample-output.txt).

## Next Steps

* Trigger a rollback and check its trace.

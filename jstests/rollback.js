const rst = new ReplSetTest({
    nodes: [{rsConfig: {priority: 3}}, {}, {rsConfig: {priority: 0}}],
    oplogSize: 999999,  // We don't model truncation in our specs, so disable it
    nodeOptions: {
        useLogFiles: true,
        setParameter: {
            "failpoint.logForTLAPlusSpecs":
                tojson({mode: "alwaysOn", data: {specs: ["RaftMongo"]}}),
            logComponentVerbosity: tojsononeline({tlaPlusTrace: 2}),
        }
    }
});

rst.startSet();
// Skip ReplSetTest's usual logic of initiating a 1-node set and adding the
// others: RaftMongo.tla doesn't support 1-node sets.
assert.commandWorked(rst.nodes[0].getDB('admin').runCommand({
    replSetInitiate: rst.getReplSetConfig()}));

rst.awaitSecondaryNodes();
rst.waitForState(rst.nodes[0], ReplSetTest.State.PRIMARY);

for (let i of [1, 2]) {
    assert.commandWorked(
        rst.nodes[i].adminCommand({
            configureFailPoint: "rsSyncApplyStop",
            mode: "alwaysOn"
        }));
}

rst.nodes[0].getDB('test').collection.insertOne({_id: 0});
checkLog.contains(rst.nodes[0], "ClientWrite");

rst.stop(0);

for (let i of [1, 2]) {
    assert.commandWorked(
        rst.nodes[i].adminCommand({
            configureFailPoint: "rsSyncApplyStop",
            mode: "off"
        }));
}

rst.waitForState(1, ReplSetTest.State.PRIMARY);
rst.nodes[1].getDB('test').collection.insertOne({_id: 1});

rst.restart(0);
rst.waitForState(0, ReplSetTest.State.PRIMARY);

checkLog.contains(rst.nodes[0], '"action" : "RollbackOplog"');

jsTestLog(`${rst.nodes[0]} oplog`);
rst.nodes[0].getDB('local').getCollection('oplog.rs').find().pretty().shellPrint();

jsTestLog(`${rst.nodes[1]} oplog`);
rst.nodes[0].getDB('local').getCollection('oplog.rs').find().pretty().shellPrint();

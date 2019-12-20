const rst = new ReplSetTest({
    nodes: [{}, {rsConfig: {priority: 0}}],
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
const db = rst.getPrimary().getDB('test');
const wc = {w: 'majority', wtimeout: 10000};
jsTestLog("single insert");
printjson(assert.commandWorked(db.runCommand({
    insert: 'collection',
    documents: [{_id: 0}],
    writeConcern: wc
})));
jsTestLog("bulk insert");
printjson(assert.commandWorked(db.runCommand({
    insert: 'collection',
    documents: [{_id: 1}, {_id: 2}],
    writeConcern: wc
})));

jsTestLog(`primary oplog`);
rst.nodes[0].getDB('local').getCollection('oplog.rs').find().pretty().shellPrint();

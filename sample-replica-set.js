const rst = new ReplSetTest({
    nodes: 3,
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
// Skip ReplSetTest's usual logic of initiating a 1-node set and adding the others: we want as
// simple a startup sequence as possible.
const config = rst.getReplSetConfig();
jsTestLog(`reconfig: ${tojson(config)}`);
assert.commandWorked(rst.nodes[0].getDB('admin').runCommand({replSetInitiate: config}));
const collection = rst.getPrimary().getDB('test').collection;
const wc = {
    writeConcern: {w: 'majority', wtimeout: 10000}
};
jsTestLog("single insert");
printjson(assert.commandWorked(collection.insert({_id: 0}, wc)));
jsTestLog("bulk insert");
printjson(assert.commandWorked(collection.insertMany([{_id: 1}, {_id: 2}], wc)));

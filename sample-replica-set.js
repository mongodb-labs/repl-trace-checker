const rst = new ReplSetTest({
  nodes: 3,
  nodeOptions: {
    useLogFiles: true,
    setParameter: {logComponentVerbosity: tojsononeline({tlaPlusTrace: 1})}
  }
});
rst.startSet();
rst.initiate();
rst.getPrimary();

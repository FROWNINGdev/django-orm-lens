// Barrel for the model parser. The implementation lives in three modules:
//   modelParse.ts    — turns one models file into ParsedModel[] (no I/O)
//   modelGraph.ts    — relation graph, neighborhoods, diagram projections
//   workspaceScan.ts — file discovery, import following, scanWorkspace
// Mirrors cli/orm_synapse/parser.py; keep the two in step.
export * from './modelParse';
export * from './modelGraph';
export * from './workspaceScan';

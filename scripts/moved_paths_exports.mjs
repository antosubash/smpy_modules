// The export surface of TypeScript files, for scripts/moved_paths.py (#319).
//
// Reads {"projects": [{"tsconfig": "...", "files": ["..."]}]} on stdin and
// prints {"<file>": {"default": bool, "exports": {"<name>": {"kind", "decl"}}}}.
// The TypeScript checker resolves `export *`, re-export chains and `@/` paths,
// so the surface is what an importer really sees. `kind` is "type" for a name
// that only exists as a type, or that some link of its re-export chain marks
// `export type`: a stub must re-export those with `export type`, or a bundler
// that compiles one file at a time emits an import that does not exist.
// `decl` is the file that declares the name.
import { SyntaxKind } from 'typescript/unstable/ast';
import { API, SymbolFlags } from 'typescript/unstable/sync';

const TYPE_ONLY_KINDS = new Set(['ExportSpecifier', 'ImportSpecifier', 'ImportClause']);

function typeOnlyLink(checker, symbol) {
  for (let link = symbol, hops = 0; link && hops < 8; hops += 1) {
    for (const handle of link.declarations ?? []) {
      const node = handle.resolve();
      if (!node || !TYPE_ONLY_KINDS.has(SyntaxKind[node.kind])) continue;
      if (node.isTypeOnly || node.parent?.isTypeOnly || node.parent?.parent?.isTypeOnly) {
        return true;
      }
    }
    if (!(link.flags & SymbolFlags.Alias)) return false;
    link = checker.getImmediateAliasedSymbol(link);
  }
  return false;
}

function surface(project, file) {
  const { checker } = project;
  const source = project.program.getSourceFile(file);
  const moduleSymbol = source && checker.getSymbolAtLocation(source);
  if (!moduleSymbol) return null;
  const result = { default: false, exports: {} };
  for (const symbol of checker.getExportsOfModule(moduleSymbol)) {
    if (symbol.name === 'default') {
      result.default = true;
      continue;
    }
    const target = symbol.flags & SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
    const known = !checker.isUnknownSymbol(target);
    const value = known ? Boolean(target.flags & SymbolFlags.Value) : true;
    const typeOnly = !value || typeOnlyLink(checker, symbol);
    const decl = known ? (target.declarations?.[0]?.path ?? null) : null;
    result.exports[symbol.name] = { kind: typeOnly ? 'type' : 'value', decl };
  }
  return result;
}

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const api = new API({ cwd: process.cwd() });
  const out = {};
  try {
    for (const { tsconfig, files } of request.projects) {
      const snapshot = api.updateSnapshot({ openProjects: [tsconfig] });
      const project = snapshot.getProject(tsconfig);
      if (!project) throw new Error(`cannot open ${tsconfig}`);
      for (const file of files) out[file] = surface(project, file);
      api.updateSnapshot({ closeProjects: [tsconfig] });
    }
  } finally {
    api.close();
  }
  process.stdout.write(JSON.stringify(out));
}

await main();

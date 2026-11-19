// License gate for the npm production dependencies, the JavaScript twin of tools/check_licenses.py.
// node scripts/check-licenses.mjs [package-lock.json]
// Reads every non-dev package of the lockfile (all platforms' optional binaries too) and fails on any SPDX identifier
// that is not on ALLOWED. No install needed: npm writes each package's `license` field into the lockfile.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// permissive licenses that allow commercial use; nothing copyleft (GPL, LGPL, AGPL, MPL) and nothing non-commercial
export const ALLOWED = new Set(["MIT", "MIT-0", "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0", "Zlib", "CC0-1.0", "Unlicense", "BlueOak-1.0.0", "Python-2.0"]);

// data packages under an attribution-only license (no copyleft): caniuse-lite (browser support tables, build time only)
export const ALLOWED_DATA = new Set(["CC-BY-4.0"]);

// packages whose lockfile entry has no `license` field, checked by hand in their LICENSE file
export const CHECKED_BY_HAND = { "webgl-constants@1.1.1": "MIT" };

/** SPDX expression -> nested ["AND"|"OR", parts] or one identifier. `X WITH exception` is judged by X. */
export function parse(expression) {
  const tokens = expression.match(/\(|\)|[^\s()]+/g) ?? [];
  let pos = 0;
  const peek = () => tokens[pos];
  const take = () => tokens[pos++];
  function factor() {
    if (peek() === "(") {
      take();
      const inner = either();
      if (take() !== ")") throw new Error(`unbalanced parentheses in "${expression}"`);
      return inner;
    }
    const id = take();
    if (id === undefined || ["AND", "OR", "WITH", ")"].includes(id)) throw new Error(`bad license expression "${expression}"`);
    if (peek() === "WITH") {
      take();
      take();
    }
    return id;
  }
  function chain(op, next) {
    const parts = [next()];
    while (peek() === op) {
      take();
      parts.push(next());
    }
    return parts.length === 1 ? parts[0] : [op, parts];
  }
  const both = () => chain("AND", factor);
  const either = () => chain("OR", both);
  const tree = either();
  if (pos !== tokens.length) throw new Error(`bad license expression "${expression}"`);
  return tree;
}

/** -> offending identifiers ([] = allowed). AND needs every part; OR needs one, since the licensee may pick it. */
export function offending(node, allowed) {
  if (typeof node === "string") return allowed.has(node) ? [] : [node];
  const [op, parts] = node;
  const results = parts.map((p) => offending(p, allowed));
  const ok = op === "AND" ? results.every((r) => r.length === 0) : results.some((r) => r.length === 0);
  return ok ? [] : results.flat();
}

/** Lockfile -> rows { name, version, license, problem } for every production package. */
export function checkLockfile(lock) {
  const allowed = new Set([...ALLOWED, ...ALLOWED_DATA]);
  const rows = [];
  for (const [path, entry] of Object.entries(lock.packages ?? {})) {
    if (path === "" || entry.dev || entry.link) continue;
    const name = entry.name ?? path.split("node_modules/").at(-1);
    const id = `${name}@${entry.version}`;
    const license = entry.license ?? CHECKED_BY_HAND[id];
    let problem = null;
    if (!license) problem = "no license field";
    else {
      try {
        const bad = offending(parse(license), allowed);
        if (bad.length) problem = `not allowed: ${bad.join(", ")}`;
      } catch (e) {
        problem = e.message;
      }
    }
    rows.push({ name, version: entry.version, license: license ?? "UNKNOWN", problem });
  }
  return rows.sort((a, b) => a.name.localeCompare(b.name));
}

function main(lockPath) {
  const rows = checkLockfile(JSON.parse(readFileSync(lockPath, "utf8")));
  for (const r of rows) console.log(`${r.problem ? "FAIL" : "ok  "} ${r.name.padEnd(44)} ${String(r.version).padEnd(12)} ${r.license}`);
  const failed = rows.filter((r) => r.problem);
  if (failed.length) {
    console.log(`\nLICENSE GATE FAILED (scripts/check-licenses.mjs):\n  ${failed.map((r) => `${r.name} ${r.version}: ${r.problem}`).join("\n  ")}`);
    return 1;
  }
  console.log(`\nLICENSES OK (${rows.length} production packages)`);
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = main(process.argv[2] ?? "package-lock.json");
}

// Fails when src/api/schema.d.ts is not what openapi-typescript makes of src/api/openapi.json.
// openapi.json itself is checked against the service by server/tests/test_openapi.py (python -m server.export_openapi).
// node scripts/check-api-types.mjs        regenerate: npm run api:types
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const out = join("node_modules", ".cache", "api-check", "schema.d.ts");
mkdirSync(join("node_modules", ".cache", "api-check"), { recursive: true });
execFileSync(process.execPath, [join("node_modules", "openapi-typescript", "bin", "cli.js"), "src/api/openapi.json", "-o", out], {
  stdio: "ignore",
});
const normalize = (s) => s.replace(/\r\n/g, "\n");
if (normalize(readFileSync(out, "utf8")) !== normalize(readFileSync("src/api/schema.d.ts", "utf8"))) {
  console.error("src/api/schema.d.ts is out of date: run `npm run api:types` (after `python -m server.export_openapi`)");
  process.exitCode = 1;
} else {
  console.log("API types up to date");
}

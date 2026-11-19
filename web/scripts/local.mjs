// Starts the review service and the web dev server together; Ctrl+C stops both.
// npm run local -- <character.json or folder>... [--fake] [--port 8765] [other `python -m server` flags]
// The web app gets NEXT_PUBLIC_API_BASE=http://127.0.0.1:<port>; WEB_PORT picks its port (default 3000).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(web, "..");
const args = process.argv.slice(2);
if (args.length === 0 || args.includes("--help")) {
  console.log("usage: npm run local -- <character.json or folder>... [--fake] [--port 8765]");
  process.exit(args.length === 0 ? 1 : 0);
}
const portAt = args.indexOf("--port");
const apiPort = portAt >= 0 ? args[portAt + 1] : "8765";
const webPort = process.env.WEB_PORT ?? "3000";
const venv = join(repo, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3";
// paths are given relative to where npm was run (INIT_CWD), the service runs from the repository root
const cwd = process.env.INIT_CWD ?? process.cwd();
const serverArgs = args.map((a, i) => (a.startsWith("--") || args[i - 1]?.startsWith("--") ? a : resolve(cwd, a)));
const origins = [`http://localhost:${webPort}`, `http://127.0.0.1:${webPort}`].flatMap((o) => ["--origin", o]);

const children = [
  spawn(python, ["-m", "server", ...serverArgs, ...origins], { cwd: repo, stdio: "inherit" }),
  spawn(process.execPath, [join(web, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", webPort], {
    cwd: web,
    stdio: "inherit",
    env: { ...process.env, NEXT_PUBLIC_API_BASE: `http://127.0.0.1:${apiPort}` },
  }),
];
console.log(`review service http://127.0.0.1:${apiPort} · web http://localhost:${webPort}/characters/`);
const stop = () => children.forEach((c) => c.exitCode === null && c.kill());
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
children.forEach((c) =>
  c.on("exit", (code) => {
    stop();
    process.exitCode = code ?? 0;
  }),
);

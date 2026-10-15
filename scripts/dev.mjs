// Starts the FastAPI backend and the Vite frontend on localhost, with prefixed logs.
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setup, venvPython, withCompatibleNode } from "./setup.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const apiPort = process.env.STRAT_API_PORT ?? "8000";
const webPort = process.env.STRAT_WEB_PORT ?? "5173";

const node = withCompatibleNode({
  ...process.env,
  STRAT_API_PORT: apiPort,
  STRAT_WEB_PORT: webPort,
});

setup();

const procs = [];
function start(name, color, cmd, args, cwd) {
  const p = spawn(cmd, args, {
    cwd,
    env: node.env,
    shell: process.platform === "win32",
  });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk;
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) out.write(prefix + line + "\n");
    });
  };
  pipe(p.stdout, process.stdout);
  pipe(p.stderr, process.stderr);
  p.on("exit", (code) => {
    console.log(`${prefix}exited with code ${code}`);
    shutdown(code ?? 0);
  });
  procs.push(p);
}

let stopping = false;
function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const p of procs) p.kill("SIGTERM");
  setTimeout(() => process.exit(code), 300);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

start("api", "36", venvPython, ["-m", "uvicorn", "strat.api:app", "--host", "127.0.0.1", "--port", apiPort], join(root, "backend"));
start("web", "35", node.npm, ["run", "dev"], join(root, "web"));
console.log(`\n  Strat Scanner → http://127.0.0.1:${webPort}  (API on 127.0.0.1:${apiPort})\n`);

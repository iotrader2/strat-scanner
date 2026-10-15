// Idempotent local setup: Python venv + backend deps, and web node_modules.
// Re-runs pip / npm only when requirements.txt or web/package.json changed.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const web = join(root, "web");
const isWin = process.platform === "win32";

export const venvPython = join(backend, ".venv", isWin ? "Scripts/python.exe" : "bin/python");

const hash = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");
const run = (cmd, args, cwd, env = process.env) =>
  execFileSync(cmd, args, { cwd, stdio: "inherit", shell: isWin, env });

// Vite 8 needs Node 20.19+ or 22.12+ (`styleText` from node:util, plus a native rolldown binding).
function viteNodeOk(version) {
  const [major, minor] = version.split(".").map(Number);
  return (major === 20 && minor >= 19) || major > 22 || (major === 22 && minor >= 12);
}

let compatibleNodeBin;
function findViteNodeBin() {
  if (compatibleNodeBin !== undefined) return compatibleNodeBin;
  if (viteNodeOk(process.versions.node)) {
    compatibleNodeBin = null;
    return null;
  }
  const nvmRoot = join(process.env.NVM_DIR ?? join(homedir(), ".nvm"), "versions/node");
  const candidates = [];
  if (existsSync(nvmRoot)) {
    for (const name of readdirSync(nvmRoot)) {
      const version = name.replace(/^v/, "");
      const bin = join(nvmRoot, name, "bin");
      if (viteNodeOk(version) && existsSync(join(bin, "node"))) candidates.push({ version, bin });
    }
  }
  candidates.sort((a, b) => {
    const pa = a.version.split(".").map(Number);
    const pb = b.version.split(".").map(Number);
    for (let i = 0; i < 3; i++) {
      const diff = (pb[i] ?? 0) - (pa[i] ?? 0);
      if (diff) return diff;
    }
    return 0;
  });
  if (!candidates.length) {
    throw new Error(
      `Node.js 20.19+ or 22.12+ is required for the UI (current is ${process.versions.node}).`,
    );
  }
  console.log(`[setup] Node ${process.versions.node} cannot run Vite; using ${candidates[0].version}`);
  compatibleNodeBin = candidates[0].bin;
  return compatibleNodeBin;
}

export function withCompatibleNode(env = process.env) {
  const bin = findViteNodeBin();
  if (!bin) return { env, npm: "npm" };
  return {
    env: { ...env, PATH: `${bin}${delimiter}${env.PATH ?? ""}` },
    npm: join(bin, isWin ? "npm.cmd" : "npm"),
  };
}

function findPython() {
  // macOS often has Apple's python3 (too old) on PATH while Homebrew only
  // exposes a versioned binary such as python3.11.
  const versioned = ["python3.14", "python3.13", "python3.12", "python3.11", "python3.10"];
  for (const candidate of [process.env.PYTHON, "python3", "python", ...versioned].filter(Boolean)) {
    try {
      const v = execFileSync(candidate, ["-c", "import sys; print(sys.version_info >= (3, 10))"], {
        encoding: "utf8",
        shell: isWin,
      });
      if (v.trim() === "True") return candidate;
    } catch {
      // try the next candidate
    }
  }
  throw new Error("Python 3.10+ is required (set PYTHON=/path/to/python3 if it is not on PATH).");
}

export function setup() {
  if (!existsSync(venvPython)) {
    console.log("[setup] creating backend/.venv");
    run(findPython(), ["-m", "venv", ".venv"], backend);
  }
  const reqStamp = join(backend, ".venv", ".requirements.sha256");
  const reqHash = hash(join(backend, "requirements.txt"));
  if (!existsSync(reqStamp) || readFileSync(reqStamp, "utf8") !== reqHash) {
    console.log("[setup] installing Python requirements");
    run(venvPython, ["-m", "pip", "install", "--quiet", "--upgrade", "pip"], backend);
    run(venvPython, ["-m", "pip", "install", "--quiet", "-r", "requirements.txt"], backend);
    writeFileSync(reqStamp, reqHash);
  }

  const pkgStamp = join(web, "node_modules", ".package.sha256");
  const pkgHash = hash(join(web, "package-lock.json"));
  if (!existsSync(pkgStamp) || readFileSync(pkgStamp, "utf8") !== pkgHash) {
    console.log("[setup] installing web dependencies");
    const node = withCompatibleNode();
    run(node.npm, ["ci", "--no-audit", "--no-fund"], web, node.env);
    writeFileSync(pkgStamp, pkgHash);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  setup();
  console.log("[setup] done");
}

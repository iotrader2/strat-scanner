// Idempotent local setup: Python venv + backend deps, and web node_modules.
// Re-runs pip / npm only when requirements.txt or web/package.json changed.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const web = join(root, "web");
const isWin = process.platform === "win32";

export const venvPython = join(backend, ".venv", isWin ? "Scripts/python.exe" : "bin/python");

const hash = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");
const run = (cmd, args, cwd) => execFileSync(cmd, args, { cwd, stdio: "inherit", shell: isWin });

function findPython() {
  for (const candidate of [process.env.PYTHON, "python3", "python"].filter(Boolean)) {
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
    run("npm", ["ci", "--no-audit", "--no-fund"], web);
    writeFileSync(pkgStamp, pkgHash);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  setup();
  console.log("[setup] done");
}

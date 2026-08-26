import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const writableTempRoot = process.platform === "win32" ? tmpdir() : "/tmp";

function assertSpawned(result) {
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
}

test("Node env files implement process > personal .env > team .env.local", async (t) => {
  const fixtureRoot = await mkdtemp(path.join(writableTempRoot, "frontend-env-"));
  t.after(() => rm(fixtureRoot, { recursive: true, force: true }));

  const teamEnv = path.join(fixtureRoot, ".env.local");
  const personalEnv = path.join(fixtureRoot, ".env");
  await writeFile(
    teamEnv,
    "TEAM_ONLY=team\nPERSONAL_WINS=team\nPROCESS_WINS=team\n",
    "utf8",
  );
  await writeFile(personalEnv, "PERSONAL_WINS=personal\nPROCESS_WINS=personal\n", "utf8");

  const result = spawnSync(
    process.execPath,
    [
      `--env-file=${teamEnv}`,
      `--env-file-if-exists=${personalEnv}`,
      "-p",
      "JSON.stringify([process.env.TEAM_ONLY, process.env.PERSONAL_WINS, process.env.PROCESS_WINS])",
    ],
    {
      encoding: "utf8",
      env: { ...process.env, PROCESS_WINS: "process" },
    },
  );

  assertSpawned(result);
  assert.deepEqual(JSON.parse(result.stdout), ["team", "personal", "process"]);
});

test("missing personal .env is optional", async (t) => {
  const fixtureRoot = await mkdtemp(path.join(writableTempRoot, "frontend-env-"));
  t.after(() => rm(fixtureRoot, { recursive: true, force: true }));

  const teamEnv = path.join(fixtureRoot, ".env.local");
  await writeFile(teamEnv, "TEAM_ONLY=team\n", "utf8");

  const result = spawnSync(
    process.execPath,
    [
      `--env-file=${teamEnv}`,
      `--env-file-if-exists=${path.join(fixtureRoot, ".env")}`,
      "-p",
      "process.env.TEAM_ONLY",
    ],
    { encoding: "utf8" },
  );

  assertSpawned(result);
  assert.equal(result.stdout.trim(), "team");
});

test("Vite and release scripts use the approved env-file order", async () => {
  const packageJson = JSON.parse(await readFile(path.join(frontendRoot, "package.json"), "utf8"));
  const expectedPrefix = "node --env-file=.env.local --env-file-if-exists=.env";

  for (const scriptName of ["dev", "build", "preview", "test:release"]) {
    assert.ok(
      packageJson.scripts[scriptName].startsWith(expectedPrefix),
      `${scriptName} must load the team env before the optional personal env`,
    );
  }
});

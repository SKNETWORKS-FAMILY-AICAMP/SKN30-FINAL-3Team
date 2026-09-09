import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";

const suite = process.argv[2];
if (!["fast", "browser"].includes(suite)) throw new Error("Choose fast or browser.");
const files = readdirSync(new URL("../tests/", import.meta.url))
  .filter((name) => /\.test\.(?:ts|mjs)$/.test(name))
  .filter((name) => suite === "browser"
    ? name.endsWith(".browser.test.mjs")
    : !name.endsWith(".browser.test.mjs") && name !== "release-build.test.mjs")
  .sort()
  .map((name) => `tests/${name}`);
if (files.length === 0) throw new Error(`No ${suite} tests found.`);
console.log(`${suite}: ${files.length} test files`);
// Browser files start Vite with different environment settings. Serialize their processes so
// dependency optimization cannot race in the shared Vite cache.
const result = spawnSync(process.execPath, ["--test", ...(suite === "browser" ? ["--test-concurrency=1"] : []), ...files], {
  cwd: new URL("../", import.meta.url), stdio: "inherit",
});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;

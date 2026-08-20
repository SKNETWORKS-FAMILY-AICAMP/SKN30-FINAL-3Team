import assert from "node:assert/strict";
import { access, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const buildRoot = path.join(frontendRoot, "dist", "client");

test("release build contains an entry document and hashed assets", async () => {
  const entryPath = path.join(buildRoot, "index.html");
  await access(entryPath);

  const entry = await readFile(entryPath, "utf8");
  assert.match(entry, /\/assets\/[^"']+\.(?:js|css)/);

  const assetRoot = path.join(buildRoot, "assets");
  const assets = await readdir(assetRoot);
  assert.ok(assets.some((name) => /-[A-Za-z0-9_-]+\.js$/.test(name)));
  assert.ok(assets.some((name) => /-[A-Za-z0-9_-]+\.css$/.test(name)));

  for (const asset of assets) {
    const details = await stat(path.join(assetRoot, asset));
    assert.ok(details.isFile());
    assert.ok(details.size > 0);
  }
});

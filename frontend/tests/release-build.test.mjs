import assert from "node:assert/strict";
import { access, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseAppEnv } from "../src/config/envSchema.ts";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const buildRoot = process.env.FRONTEND_DIST_DIR
  ? path.resolve(process.env.FRONTEND_DIST_DIR)
  : path.join(frontendRoot, "dist", "client");

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

test("release JavaScript contains only the validated same-origin API configuration", async () => {
  const { apiBaseUrl } = parseAppEnv(process.env);

  const assetRoot = path.join(buildRoot, "assets");
  const assets = await readdir(assetRoot);
  const javascript = (
    await Promise.all(
      assets
        .filter((name) => name.endsWith(".js"))
        .map((name) => readFile(path.join(assetRoot, name), "utf8")),
    )
  ).join("\n");

  assert.ok(javascript.includes(apiBaseUrl), `release bundle must contain ${apiBaseUrl}`);

  for (const backendOrigin of [
    process.env.FRONTEND_BACKEND_ORIGIN,
    process.env.VITE_BACKEND_ORIGIN,
  ]) {
    if (backendOrigin) {
      assert.ok(
        !javascript.includes(backendOrigin),
        "development backend origin must not be included in the release bundle",
      );
    }
  }
});

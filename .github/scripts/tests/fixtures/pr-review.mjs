import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL("../../../..", import.meta.url));
const event = JSON.parse(
  await readFile(
    path.join(rootDir, ".github/scripts/tests/fixtures/pull-request.json"),
    "utf8"
  )
);
const policy = JSON.parse(
  await readFile(path.join(rootDir, ".github/pr-review-policy.json"), "utf8")
);
const pr = event.pull_request;

function gitBlobSha(contents) {
  const bytes = Buffer.isBuffer(contents) ? contents : Buffer.from(contents, "utf8");
  return createHash("sha1")
    .update(Buffer.from(`blob ${bytes.byteLength}\0`, "utf8"))
    .update(bytes)
    .digest("hex");
}

function headFilePayload(file, contents) {
  const bytes = Buffer.isBuffer(contents) ? contents : Buffer.from(contents, "utf8");
  assert.equal(file.sha, gitBlobSha(bytes), `fixture SHA mismatch for ${file.filename}`);
  return {
    type: "file",
    sha: file.sha,
    size: bytes.byteLength,
    encoding: "base64",
    content: bytes.toString("base64")
  };
}

export { rootDir, event, policy, pr, gitBlobSha, headFilePayload };

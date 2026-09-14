import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { checkSkillDocs, measureDocuments } from "../check-skill-docs.mjs";

test("repository skill adapters, links and policy references resolve", async () => {
  assert.deepEqual((await checkSkillDocs(process.cwd())).errors, []);
});

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "skill-docs-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const write = async (filename, text) => {
    await mkdir(path.dirname(path.join(root, filename)), { recursive: true });
    await writeFile(path.join(root, filename), text);
  };
  await write(".agents/skills/example/SKILL.md", "---\nname: example\ndescription: 예시 스킬\n---\n\n[guide](references/guide.md#rules)\n");
  await write(".agents/skills/example/references/guide.md", "# Guide\n\n## Rules\n한글 😀\n");
  await write(".claude/skills/example/SKILL.md", '---\nname: example\ndescription: "예시 스킬"\n---\n\n@../../../.agents/skills/example/SKILL.md\n');
  const policy = {
    version: 2,
    cost: { serviceTier: "default" },
    policyPacks: [{
      id: "example", phases: ["leaf"], when: [{ prefixes: ["example/"] }],
      files: [{ path: ".agents/skills/example/references/guide.md", sections: ["Rules"] }]
    }]
  };
  await write(".github/pr-review-policy.json", JSON.stringify(policy));
  return { root, write, policy };
}

test("skill guard catches adapter drift, broken file links and stale policy sections", async (t) => {
  const { root, write, policy } = await fixture(t);
  assert.deepEqual((await checkSkillDocs(root)).errors, []);
  await write(".claude/skills/example/SKILL.md", '---\nname: example\ndescription: "옛 설명"\n---\n\n@../../../.agents/skills/missing/SKILL.md\n');
  await write(".agents/skills/example/references/guide.md", '# Guide\n\n## Renamed\n[missing](gone.md)\n[external](https://example.com/no-network)\n\n```md\n[example](not-a-real-file.md)\n```\n');
  policy.always = { files: [".agents/skills/example/references/deleted.md"] };
  await write(".github/pr-review-policy.json", JSON.stringify(policy));
  const errors = (await checkSkillDocs(root)).errors.join("\n");
  assert.match(errors, /description differs/u);
  assert.match(errors, /expected only @/u);
  assert.match(errors, /missing link target gone\.md/u);
  assert.match(errors, /missing policy section Rules/u);
  assert.match(errors, /deleted\.md/u);
  assert.doesNotMatch(errors, /not-a-real-file|no-network/u);
});

test("reading measurement deduplicates documents and counts Unicode characters, not tokens", async (t) => {
  const { root, write } = await fixture(t);
  await write("reading.md", "한글 😀\n");
  const result = await measureDocuments(root, ["reading.md", "reading.md"]);
  assert.deepEqual(result.totals, { files: 1, lines: 1, characters: 5 });
});

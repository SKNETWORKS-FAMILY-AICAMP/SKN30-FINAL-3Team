import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { extractMarkdownSections, validatePolicyConfig } from "./pr-review-lib.mjs";

async function markdownFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) return markdownFiles(filename);
    return entry.isFile() && entry.name.endsWith(".md") ? [filename] : [];
  }));
  return files.flat().sort();
}

function metadata(contents, field) {
  const frontmatter = contents.match(/^---\r?\n([\s\S]*?)\r?\n---/u)?.[1];
  const value = frontmatter?.match(new RegExp(`^${field}:\\s*(.+)$`, "mu"))?.[1].trim();
  if (value?.startsWith('"')) return JSON.parse(value);
  if (value?.startsWith("'")) return value.slice(1, -1).replaceAll("''", "'");
  return value;
}

// Check file destinations, not heading fragments or external URLs. Ignore code examples.
function relativeLinks(contents) {
  const prose = contents.replace(/^\s*(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\s*\1\s*$/gmu, "");
  const targets = [
    ...prose.matchAll(/\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^\n]*["'])?\s*\)/gu),
    ...prose.matchAll(/^\s*\[[^\]]+\]:\s*(?:<([^>]+)>|([^\s]+))/gmu)
  ];
  return targets.map((match) => match[1] ?? match[2])
    .filter((target) => !/^(?:[a-z][a-z\d+.-]*:|\/|#)/iu.test(target))
    .map((target) => decodeURIComponent(target.split(/[?#]/u)[0]))
    .filter(Boolean);
}

export async function checkSkillDocs(rootDir) {
  const errors = [];
  const canonicalRoot = path.join(rootDir, ".agents/skills");
  const adapterRoot = path.join(rootDir, ".claude/skills");
  const canonicalFiles = await markdownFiles(canonicalRoot);
  const adapterFiles = await markdownFiles(adapterRoot);
  const canonicalSkills = canonicalFiles.filter((file) => path.basename(file) === "SKILL.md");
  const expectedAdapters = new Set();
  for (const filename of canonicalSkills) {
    const relative = path.relative(canonicalRoot, filename);
    const adapter = path.join(adapterRoot, relative);
    expectedAdapters.add(adapter);
    try {
      const source = await readFile(filename, "utf8");
      const contents = await readFile(adapter, "utf8");
      for (const field of ["name", "description"]) {
        const expected = metadata(source, field);
        if (!expected || metadata(contents, field) !== expected) {
          errors.push(`${path.relative(rootDir, adapter)}: ${field} differs from canonical skill`);
        }
      }
      const body = contents.replace(/^---\r?\n[\s\S]*?\r?\n---/u, "").trim();
      const expectedImport = `@${path.relative(path.dirname(adapter), filename).split(path.sep).join("/")}`;
      if (body !== expectedImport) errors.push(`${path.relative(rootDir, adapter)}: expected only ${expectedImport}`);
    } catch (error) {
      errors.push(`${path.relative(rootDir, adapter)}: ${error.message}`);
    }
  }
  for (const filename of adapterFiles) {
    if (!expectedAdapters.has(filename)) errors.push(`${path.relative(rootDir, filename)}: no canonical skill adapter`);
  }
  for (const filename of canonicalFiles) {
    for (const target of relativeLinks(await readFile(filename, "utf8"))) {
      try {
        await stat(path.resolve(path.dirname(filename), target));
      } catch {
        errors.push(`${path.relative(rootDir, filename)}: missing link target ${target}`);
      }
    }
  }
  const policy = JSON.parse(await readFile(path.join(rootDir, ".github/pr-review-policy.json"), "utf8"));
  errors.push(...validatePolicyConfig(policy).reasons);
  const routes = [policy.always, policy.projectWide, ...Object.values(policy.modules ?? {}), ...policy.policyPacks];
  for (const entry of routes.flatMap((route) => route?.files ?? [])) {
    const document = typeof entry === "string" ? { path: entry } : entry;
    try {
      const contents = await readFile(path.join(rootDir, document.path), "utf8");
      const { missingSections } = extractMarkdownSections(contents, document.sections);
      for (const section of missingSections) errors.push(`${document.path}: missing policy section ${section}`);
    } catch (error) {
      errors.push(`${document.path}: ${error.message}`);
    }
  }
  return { skillCount: canonicalSkills.length, markdownCount: canonicalFiles.length, errors: [...new Set(errors)] };
}

// Supply the exact documents read for a task. Counts describe files, not model input tokens.
export async function measureDocuments(rootDir, filenames) {
  const documents = await Promise.all([...new Set(filenames)].map(async (filename) => {
    const contents = await readFile(path.resolve(rootDir, filename), "utf8");
    return {
      path: filename,
      lines: contents ? contents.replace(/\n$/u, "").split("\n").length : 0,
      characters: [...contents].length
    };
  }));
  return {
    documents,
    totals: documents.reduce((total, doc) => ({
      files: total.files + 1, lines: total.lines + doc.lines, characters: total.characters + doc.characters
    }), { files: 0, lines: 0, characters: 0 })
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const args = process.argv.slice(2);
  if (args[0] === "--measure" && args.length > 1) {
    console.log(JSON.stringify(await measureDocuments(process.cwd(), args.slice(1)), null, 2));
  } else if (args.length === 0) {
    const result = await checkSkillDocs(process.cwd());
    console.log(JSON.stringify(result, null, 2));
    if (result.errors.length) process.exitCode = 1;
  } else {
    console.error("Usage: node .github/scripts/check-skill-docs.mjs [--measure <document> ...]");
    process.exitCode = 2;
  }
}

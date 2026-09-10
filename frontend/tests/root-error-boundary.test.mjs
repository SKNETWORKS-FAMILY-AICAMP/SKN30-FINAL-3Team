import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

let vite;
let RootErrorBoundary;

before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    server: { middlewareMode: true, hmr: false },
    plugins: [react()],
    ssr: {
      noExternal: [
        "@patternfly/react-core",
        "@patternfly/react-icons",
        "@patternfly/react-styles",
      ],
    },
  });

  ({ RootErrorBoundary } = await vite.ssrLoadModule("/src/RootErrorBoundary.tsx"));
});

after(async () => {
  await vite?.close();
});

test("렌더링 오류 상태는 안전한 복구 화면으로 전환된다", () => {
  const failedState = RootErrorBoundary.getDerivedStateFromError(new Error("private detail"));
  assert.deepEqual(failedState, { failed: true });

  const boundary = new RootErrorBoundary({
    children: React.createElement("p", null, "렌더링되면 안 되는 원래 화면"),
  });
  boundary.state = failedState;

  const html = renderToStaticMarkup(boundary.render());
  assert.match(html, /화면을 표시하지 못했습니다/);
  assert.match(html, /화면 새로고침/);
  assert.doesNotMatch(html, /private detail|렌더링되면 안 되는 원래 화면|stack|Error:/);
});

test("애플리케이션 root는 App을 최상위 오류 경계로 감싼다", () => {
  const main = fs.readFileSync(path.join(frontendRoot, "src/main.jsx"), "utf8");

  assert.match(
    main,
    /<RootErrorBoundary>\s*<App\s*\/>\s*<\/RootErrorBoundary>/,
  );
});

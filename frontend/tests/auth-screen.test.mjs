import assert from "node:assert/strict";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

let vite;
let LoginMethods;

before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    server: { middlewareMode: true, hmr: false },
    plugins: [react()],
    // PatternFly의 CommonJS 진입점이 CSS를 require하므로 Vite가 함께 변환하게 한다.
    ssr: {
      noExternal: [
        "@patternfly/react-core",
        "@patternfly/react-icons",
        "@patternfly/react-styles",
      ],
    },
  });

  ({ LoginMethods } = await vite.ssrLoadModule("/src/features/auth/LoginMethods.tsx"));
});

after(async () => {
  await vite?.close();
});

function renderLoginMethods(developmentAuthEnabled) {
  return renderToStaticMarkup(
    React.createElement(LoginMethods, {
      developmentAuthEnabled,
      isSubmitting: false,
      onDevelopmentSession: () => undefined,
    }),
  );
}

test("개발 인증이 켜지면 안내와 구분선, 개발 세션 버튼을 함께 표시한다", () => {
  const html = renderLoginMethods(true);

  assert.match(html, /아이디·비밀번호 로그인은 아직 제공하지 않습니다/);
  assert.match(html, /개발용 세션으로 로그인/);
  assert.match(html, /<hr\b/);
});

test("개발 인증이 꺼지면 개발 진입점을 숨기고 사용할 방식이 없음을 알린다", () => {
  const html = renderLoginMethods(false);

  assert.match(html, /현재 사용할 수 있는 로그인 방식이 없습니다/);
  assert.doesNotMatch(html, /개발용 세션으로 로그인/);
  assert.doesNotMatch(html, /<hr\b/);
});

test("두 설정 모두 비활성 자격증명 폼을 유지한다", () => {
  for (const enabled of [true, false]) {
    const html = renderLoginMethods(enabled);

    assert.match(html, /id="login-id"[^>]*disabled/);
    assert.match(html, /id="login-password"[^>]*disabled/);
  }
});

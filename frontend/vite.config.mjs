import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

import { APP_ENV_KEYS, parseAppEnv } from "./src/config/envSchema.ts";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const allowedEnvFiles = new Set([".env", ".env.example", ".env.local"]);

export function findForbiddenProfileEnvFiles(fileNames) {
  return fileNames
    .filter((name) => name.startsWith(".env.") && !allowedEnvFiles.has(name))
    .sort();
}

export function parseBackendOrigin(value) {
  const rawValue = value?.trim() || "http://127.0.0.1:8000";
  let parsed;

  try {
    parsed = new URL(rawValue);
  } catch {
    throw new Error("FRONTEND_BACKEND_ORIGIN must be an absolute http(s) origin");
  }

  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.pathname !== "/" ||
    parsed.search !== "" ||
    parsed.hash !== ""
  ) {
    throw new Error("FRONTEND_BACKEND_ORIGIN must be an absolute http(s) origin");
  }

  return parsed.origin;
}

export default defineConfig(() => {
  const forbiddenEnvFiles = findForbiddenProfileEnvFiles(readdirSync(frontendRoot));
  if (forbiddenEnvFiles.length > 0) {
    throw new Error(
      `Profile env files are not supported: ${forbiddenEnvFiles.join(", ")}. ` +
        "Use tracked .env.local, ignored .env, or process environment variables.",
    );
  }

  const backendOrigin = parseBackendOrigin(process.env.FRONTEND_BACKEND_ORIGIN);
  const source = Object.fromEntries(APP_ENV_KEYS.map((key) => [key, process.env[key]]));
  const appEnv = parseAppEnv(source);
  const browserEnv = {
    VITE_AUTH_DEVELOPMENT_ENABLED: String(appEnv.authDevelopmentEnabled),
    VITE_LEDGER_SOURCE: appEnv.ledgerSource,
    // 지정하지 않으면 `parseAppEnv`가 장부 출처로 채운 값이 들어온다.
    VITE_F3_SOURCE: appEnv.f3Source,
    VITE_CALENDAR_SOURCE: appEnv.calendarSource,
    VITE_API_BASE_URL: appEnv.apiBaseUrl,
    VITE_MOCK_ROW_COUNT: String(appEnv.mockRowCount),
    VITE_MOCK_LATENCY_MS: String(appEnv.mockLatencyMs),
  };

  return {
    build: {
      outDir: "dist/client",
    },
    // npm scripts load .env.local and optional .env with Node. Disabling Vite's
    // profile loader keeps one explicit precedence: process > .env > .env.local.
    envDir: false,
    // Only validated keys are explicitly defined. An obsolete or accidental
    // VITE_ variable therefore cannot leak into the browser bundle.
    envPrefix: "FRONTEND_NO_AUTOMATIC_BROWSER_ENV_",
    define: Object.fromEntries(
      Object.entries(browserEnv).map(([key, value]) => [
        `import.meta.env.${key}`,
        JSON.stringify(value),
      ]),
    ),
    optimizeDeps: {
      include: ["react", "react-dom/client"],
    },
    server: {
      host: "0.0.0.0",
      allowedHosts: ["terminal.local"],
      proxy: {
        "/api": {
          target: backendOrigin,
          changeOrigin: true,
        },
      },
      warmup: {
        clientFiles: ["./src/main.jsx"],
      },
    },
    plugins: [react()],
  };
});

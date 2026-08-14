# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Durable F1·F2·F3 UI Decisions

Read the repository-root `DESIGN.md`, `SCREEN_MATRIX_F1_F2_F3.md`, and `PROTOTYPE_ASSUMPTIONS.md` before changing product behavior.

- F1 owns the single detail Modal, save/close decisions, security gates, and copy-only message composer.
- F1 ledger Pages use a compact two-strip workbook layout: identity/ledger switch/search on the first strip, actions/filters/state/secondary work on the second, then a full-width Grid. Do not restore a persistent left nav or large page hero on `F1-PG-010/020`; keep overflow inside the second strip.
- F2 remains a Panel inside the F1 detail. Expose a prominent detail-header voice-entry action that scrolls and focuses that Panel; do not add an F2 Page or Modal.
- F3 individual judgment remains a nonblocking detail Panel. Batch campaigns may use the F1 Shell Page and must return to the F1 message composer.
- For selected rows, provide an explicit one-step `전체 선택 해제`; preserve filter, sort, and scroll.
- Split `문자 작업` from `F3 캠페인`; both end at target confirmation and phone-number copying in MVP. Never add a send CTA without an approved adapter requirement.
- New-complex quick add belongs inside the new-row F1 detail and must return the created master value to the current draft.
- Data migration is retired from the active product and prototype. Its former requirements, screen implementation, captures, and test evidence live under `archive/data-migration/`; do not restore an entry point without a new PO decision.
- Keep prototype-only state controls in secondary disclosure, expose one primary action per decision step, and provide section orientation in the long F1 detail.
- Consultation log `①②③` marks the registration order of multiple people in the same role. Require an explicit person choice, keep missing choice unspecified, and apply the same rule to F2/F3-generated logs.
- Visible text must be at least 12px. Validate 1600×900 and 1366×768.
- Do not promote prototype capacity, timing, retention, threshold, security-regex, or fixture values to requirements. Register them in the assumption files.


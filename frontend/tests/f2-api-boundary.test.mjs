import assert from "node:assert/strict";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const originalFetch = globalThis.fetch;

let vite;
let analyzeVoiceMemo;
let analyzeNewIntake;
let setCsrfToken;
let ApiError;
let describeF2Error;

before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    logLevel: "silent",
    server: { middlewareMode: true, hmr: false },
  });

  ({ analyzeNewIntake, analyzeVoiceMemo } = await vite.ssrLoadModule(
    "/src/features/f2/api/f2Api.ts",
  ));
  ({ setCsrfToken } = await vite.ssrLoadModule("/src/shared/api/session.ts"));
  ({ ApiError } = await vite.ssrLoadModule("/src/shared/api/errors.ts"));
  ({ describeF2Error } = await vite.ssrLoadModule("/src/features/f2/api/errors.ts"));
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  setCsrfToken(null);
});

after(async () => {
  await vite?.close();
});

test("F2 multipart fetch 실패도 공통 ApiError와 안전한 화면 문구로 이어진다", async () => {
  setCsrfToken("csrf-for-test");
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(
      JSON.stringify({
        code: "F2_UNAVAILABLE",
        message: "private provider endpoint and response",
        request_id: "123e4567-e89b-12d3-a456-426614174000",
      }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  };

  let caught;
  try {
    await analyzeVoiceMemo({
      audio: new File(["synthetic-audio"], "memo.wav", { type: "audio/wav" }),
      ledgerType: "property",
      draft: {},
    });
  } catch (error) {
    caught = error;
  }

  assert.ok(caught instanceof ApiError);
  assert.equal(caught.status, 503);
  assert.equal(caught.code, "F2_UNAVAILABLE");
  assert.equal(caught.requestId, "123e4567-e89b-12d3-a456-426614174000");
  assert.equal(request.url, "/api/v1/f2/analyses");
  assert.equal(request.init.method, "POST");
  assert.ok(request.init.body instanceof FormData);

  const shown = describeF2Error(caught);
  assert.match(shown, /음성 분석 서비스를 현재 사용할 수 없습니다/);
  assert.match(shown, /요청 번호 123e4567-e89b-12d3-a456-426614174000/);
  assert.doesNotMatch(shown, /private provider endpoint|response/);
});

test("신규 매수문의는 현재 장부 없이 한 번만 요청하고 구입장 필드를 받는다", async () => {
  setCsrfToken("csrf-for-test");
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return new Response(
      JSON.stringify({
        consultation_type: "매수문의",
        ledger_type: "구입장",
        ledger_mismatch: false,
        proposals: [
          {
            field_name: "희망 단지",
            current_value: null,
            proposed_value: "한강아파트",
            evidence: "한강아파트를 사고 싶어요",
            status: "확인됨",
            selected_by_default: true,
          },
        ],
        uncertainties: [],
        consultation_log_draft: "한강아파트 매수 문의.",
        privacy_confirmed_at: "2026-09-07T00:00:00Z",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  const result = await analyzeNewIntake({
    audio: new File(["synthetic-audio"], "memo.wav", { type: "audio/wav" }),
  });

  assert.equal(requests.length, 1);
  const form = requests[0].init.body;
  assert.equal(form.get("current_ledger_type"), null);
  assert.equal(form.get("ledger_type"), null);
  assert.equal(result.consultationType, "매수문의");
  assert.equal(result.ledgerType, "buyer");
  assert.equal(result.proposals[0].fieldKey, "complex");
  assert.equal(result.usedFallbackLedger, false);
});

function respondWith(body) {
  globalThis.fetch = async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
}

const strayProposal = {
  field_name: "희망 단지",
  current_value: null,
  proposed_value: "한강아파트",
  evidence: "한강아파트를 사고 싶어요",
  status: "확인됨",
  selected_by_default: true,
};

test("장부 불일치 응답의 필드 제안은 현재 장부 draft에 반영하지 않는다", async () => {
  setCsrfToken("csrf-for-test");
  respondWith({
    consultation_type: "매수문의",
    ledger_type: "구입장",
    ledger_mismatch: true,
    proposals: [strayProposal],
    uncertainties: ["현재 장부와 상담 유형이 다릅니다."],
    consultation_log_draft: "한강아파트 매수 문의.",
    privacy_confirmed_at: "2026-09-07T00:00:00Z",
  });

  const result = await analyzeVoiceMemo({
    audio: new File(["synthetic-audio"], "memo.wav", { type: "audio/wav" }),
    ledgerType: "property",
    draft: {},
  });

  assert.equal(result.ledgerMismatch, true);
  assert.equal(result.proposals.length, 1);
  assert.equal(result.proposals[0].id, "consultation-log");
});

test("추천 장부가 없는 기타상담의 필드 제안은 매물장으로 해석하지 않는다", async () => {
  setCsrfToken("csrf-for-test");
  respondWith({
    consultation_type: "기타상담",
    ledger_type: null,
    ledger_mismatch: false,
    proposals: [strayProposal],
    uncertainties: [],
    consultation_log_draft: "공동중개 문의.",
    privacy_confirmed_at: "2026-09-07T00:00:00Z",
  });

  const result = await analyzeNewIntake({
    audio: new File(["synthetic-audio"], "memo.wav", { type: "audio/wav" }),
  });

  assert.equal(result.usedFallbackLedger, true);
  assert.equal(result.proposals.length, 1);
  assert.equal(result.proposals[0].id, "consultation-log");
});

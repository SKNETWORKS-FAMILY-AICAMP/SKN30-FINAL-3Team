import assert from "node:assert/strict";
import { test } from "node:test";
import { LEDGER_LABEL } from "../src/features/f2/model/consultationRouting.ts";

test("장부 표기는 사용자에게 보이는 이름을 쓴다", () => {
  assert.equal(LEDGER_LABEL.property, "매물장");
  assert.equal(LEDGER_LABEL.buyer, "구입장");
});

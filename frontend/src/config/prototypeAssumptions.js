/**
 * Prototype-only values.
 *
 * These constants make the demo deterministic. They are not product policy.
 * See ../../../PROTOTYPE_ASSUMPTIONS.md before promoting any value to production.
 */
export const PROTOTYPE_ASSUMPTIONS = Object.freeze({
  audio: Object.freeze({
    maxBytes: null,
    maxLabel: null,
    oneSourcePerAnalysis: true,
    minimumRecordedSeconds: 1,
  }),
  grid: Object.freeze({
    demoRowCount: 7200,
    undoLimit: 20,
  }),
  campaign: Object.freeze({
    batchWarningCount: 8,
  }),
  timing: Object.freeze({
    f2ProcessingStepMs: 900,
    f3ProcessingStepMs: 900,
    f3CompletionDelayMs: 450,
  }),
  f2ProposalFixture: Object.freeze({
    price: "12억 8,000만 원",
    expiryOffsetMonths: 6,
    owner: "소유자 확인 필요",
    log: "임대인과 매도 조건 및 후속 연락 일정을 확인함.",
  }),
  security: Object.freeze({
    sensitivePattern: /(?:\d{6}[- ]?[1-4]\d{6})|(?:\d{2,4}[- ]?\d{2,4}[- ]?\d{4,})/,
  }),
  complexQuickAdd: Object.freeze({
    requiredFields: ["name"],
    optionalFields: ["address"],
  }),
});

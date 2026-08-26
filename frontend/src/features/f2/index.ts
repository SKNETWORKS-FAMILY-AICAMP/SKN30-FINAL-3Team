/**
 * 음성메모 분석 기능 모듈의 공개 진입점.
 *
 * 다른 기능은 이 파일이 내보내는 것만 쓴다. HTTP 계약과 상담 유형 해석이 바뀌어도
 * 화면 쪽 import 경로가 따라 흔들리지 않게 한다.
 */

export { analyzeNewIntake, analyzeVoiceMemo } from "./api/f2Api.ts";
export type { IntakeAnalysis, VoiceAnalysis, VoiceProposal } from "./api/f2Api.ts";
export { LEDGER_LABEL, routeConsultation } from "./model/consultationRouting.ts";
export type { LedgerType } from "./model/consultationRouting.ts";

/**
 * F3 교차 판정 HTTP 경계.
 *
 * 경로와 요청·응답 형태의 정본은 project-wiki `contracts/api.md`의 "F3 실행 계약"과
 * `backend/src/api/f3_runs.py`다. 화면과 훅은 경로를 알지 못하므로 계약이 바뀌어도 변경이 이
 * 파일 밖으로 번지지 않는다.
 *
 * Cookie, CSRF 헤더, 상태 코드 분류와 취소는 `shared/api`의 `request()`가 처리한다.
 */

import { request } from "../../../shared/api/index.ts";
import {
  asArray,
  asNullableNumber,
  asNullableString,
  asRecord,
  asString,
} from "../../../shared/decode/index.ts";
import {
  decodeFeedback,
  decodeRun,
  decodeRunResult,
  decodeRunStatus,
} from "../model/decode.ts";
import type {
  AnchorType,
  FeedbackDto,
  FeedbackField,
  FeedbackReason,
  RunDto,
  RunResultDto,
  RunStatusDto,
} from "../model/dto.ts";

const PATHS = {
  runs: "/f3/runs",
  feedback: "/f3/feedback",
  requirements: "/property-requirements",
} as const;

/** 후보 목록 기본 페이지 크기. 서버 기본값과 같고 상한은 100이다. */
export const DEFAULT_CANDIDATE_LIMIT = 20;
export const MAX_CANDIDATE_LIMIT = 100;

export interface RunAnchor {
  anchorType: AnchorType;
  anchorId: number;
}

export interface CandidatePage {
  limit?: number;
  offset?: number;
}

export interface NotInterestedInput {
  targetId: number;
  reason: FeedbackReason;
  fieldName?: FeedbackField;
}

/**
 * 실행을 접수하거나 같은 입력의 활성 실행 식별자를 받는다.
 *
 * 서버가 사무소·앵커 단위 advisory lock으로 직렬화하므로, F1 저장 직후에 호출해도 Backend가
 * 자동 접수한 실행과 중복되지 않는다. 먼저 잠금을 잡은 쪽이 만들고 나중은 같은 실행을 받는다.
 *
 * 응답은 202다. 실행이 끝났다는 뜻이 아니라 적재됐다는 뜻이다.
 */
export async function createRun(anchor: RunAnchor, signal?: AbortSignal): Promise<RunDto> {
  return request(PATHS.runs, {
    method: "POST",
    // 서버가 `extra="forbid"`다. 선언하지 않은 필드를 얹으면 422다.
    body: { anchor_type: anchor.anchorType, anchor_id: anchor.anchorId },
    signal,
    decode: (value) => decodeRun(value),
  });
}

/** polling용 상태 조회. 상태를 바꾸지 않으므로 CSRF 토큰을 요구하지 않는다. */
export async function getRunStatus(runId: number, signal?: AbortSignal): Promise<RunStatusDto> {
  return request(`${PATHS.runs}/${runId}`, {
    signal,
    decode: (value) => decodeRunStatus(value),
  });
}

/**
 * 실행 결과. 진행 중이면 마지막으로 저장된 안전 단계까지만 온다.
 *
 * 페이지 대상은 카드화된 상위 후보만이 아니라 결정적 SQL에 포함된 전체 후보다.
 */
export async function getRunResult(
  runId: number,
  page: CandidatePage = {},
  signal?: AbortSignal,
): Promise<RunResultDto> {
  return request(`${PATHS.runs}/${runId}/result`, {
    query: {
      limit: page.limit ?? DEFAULT_CANDIDATE_LIMIT,
      offset: page.offset ?? 0,
    },
    signal,
    decode: (value) => decodeRunResult(value),
  });
}

/**
 * 관심없음 피드백.
 *
 * `target_id`는 장부 `candidate_id`가 아니라 `match_candidate_evaluation.id`다. 두 값을 잇는
 * 정보가 아직 결과 응답에 없으므로(§12.2) 화면은 그 ID를 확보하기 전까지 이 함수를 부르지
 * 않는다. `candidate_id`를 넣어 추측하면 서버 검증은 통과하고 엉뚱한 판정 행에 저장된다.
 *
 * `feedback_type`은 서버가 `NOT_INTERESTED`로 고정하므로 보내지 않는다. 자유 메모와 정정값을
 * 받는 입력란도 없다.
 */
export async function sendNotInterested(
  input: NotInterestedInput,
  signal?: AbortSignal,
): Promise<FeedbackDto> {
  const body: Record<string, unknown> = {
    target: "MATCH_CANDIDATE",
    target_id: input.targetId,
    reason: input.reason,
  };
  if (input.fieldName != null) body["field_name"] = input.fieldName;

  return request(PATHS.feedback, {
    method: "POST",
    body,
    signal,
    decode: (value) => decodeFeedback(value),
  });
}

/**
 * 후보를 화면에 표시하기 위한 구입장 요약.
 *
 * **임시 우회다.** 결과 응답이 `candidate_id`와 금액·접수일만 주고 사람이 식별할 제목을 주지
 * 않아, LISTING 앵커의 후보를 그리려면 장부를 따로 읽어야 한다. Backend가 후보 응답에
 * `desired_complex_names`와 `desired_pyeongs`를 실어주면 이 함수와 호출부를 제거한다.
 *
 * 인물은 읽지 않는다. 상세 응답에 성명·연락처가 들어 있지만 후보 목록은 부동산·조건 값만
 * 보여주고, 문자 작성 시점에 F1이 최신 연락처와 동의를 다시 조회한다.
 */
export interface CandidateSummary {
  requirementId: number;
  demandType: string;
  desiredComplexNames: string[];
  desiredPyeongs: number[];
  maxBudgetAmount: number | null;
  budgetRawText: string | null;
}

export async function fetchCandidateSummary(
  requirementId: number,
  signal?: AbortSignal,
): Promise<CandidateSummary> {
  return request(`${PATHS.requirements}/${requirementId}`, {
    signal,
    decode: (value) => decodeCandidateSummary(value, requirementId),
  });
}

function decodeCandidateSummary(value: unknown, requirementId: number): CandidateSummary {
  const body = asRecord(value, "response");
  const requirement = asRecord(body["requirement"], "response.requirement");
  const complexes = asArray(body["desired_complexes"], "response.desired_complexes");

  const pyeongs = requirement["desired_pyeongs"];
  return {
    requirementId,
    demandType: asString(requirement["demand_type"], "response.requirement.demand_type"),
    desiredComplexNames: complexes.map((entry, index) => {
      const path = `response.desired_complexes[${index}]`;
      const complex = asRecord(asRecord(entry, path)["complex"], `${path}.complex`);
      return asString(complex["name"], `${path}.complex.name`);
    }),
    // 서버가 NUMERIC 배열을 숫자 또는 숫자 문자열로 보낼 수 있다. 둘 다 받는다.
    desiredPyeongs:
      pyeongs == null
        ? []
        : asArray(pyeongs, "response.requirement.desired_pyeongs")
            .map((entry) => Number(entry))
            .filter((entry) => Number.isFinite(entry)),
    maxBudgetAmount: asNullableNumber(
      requirement["max_budget_amount"],
      "response.requirement.max_budget_amount",
    ),
    budgetRawText: asNullableString(
      requirement["budget_raw_text"],
      "response.requirement.budget_raw_text",
    ),
  };
}

/**
 * 후보 페이지 크기.
 *
 * 서버 기본값과 상한(`backend/src/api/f3_runs.py`)에 맞춘다. transport와 훅이 함께 쓰므로
 * 어느 한쪽에 두지 않고 여기 한 곳에 둔다.
 */

export const DEFAULT_CANDIDATE_LIMIT = 20;
export const MAX_CANDIDATE_LIMIT = 100;

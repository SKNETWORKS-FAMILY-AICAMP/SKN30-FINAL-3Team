/**
 * 로그인 화면 (F1-PG-001).
 *
 * 요구사항은 사무소 계정과 담당자별 로그인(F1-SE-01), 공용 PC를 전제한 자동 잠금과 재로그인
 * (F1-SE-11)을 요구한다. 그런데 **아이디·비밀번호 로그인 계약이 아직 없다**
 * (project-wiki `contracts/api.md`: "실제 비밀번호 로그인 계약은 현재 MVP 범위에 포함하지 않는다").
 * 백엔드도 개발 계정에 사용 불가 해시를 넣어두었고 자격증명 검증 경로 자체가 없다.
 *
 * 그래서 화면은 세우되 자격증명 입력은 비활성으로 둔다. 입력을 받아놓고 제출 시점에
 * "아직 안 됩니다"라고 답하는 쪽이 더 나쁘기 때문에, 쓸 수 없다는 사실을 입력 전에 알린다.
 * 개발 세션을 표시하도록 설정한 환경에서만 그 진입 경로를 보여 준다. 계약이 확정되면 비활성
 * 폼에 상태와 제출 핸들러만 붙이면 된다.
 */

import { Alert, Button, LoginPage, Stack, StackItem } from "@patternfly/react-core";
import { APP_ENV } from "../../config/env.ts";
import { useAuth } from "./AuthContext.tsx";
import type { AnonymousReason } from "./AuthContext.tsx";
import { LoginMethods } from "./LoginMethods.tsx";

export function LoginScreen() {
  const { state, isSubmitting, notice, signInWithDevelopmentSession, recheck } = useAuth();
  const unreachable = state.status === "unreachable" ? state.message : null;
  const reason = state.status === "anonymous" ? state.reason : null;

  return (
    <LoginPage
      loginTitle="집크크 로그인"
      loginSubtitle="중개사무소 계정으로 접속합니다"
      textContent="매물장과 구입장은 사무소 단위로 분리되어 있습니다. 공용 PC에서는 자리를 비울 때 반드시 로그아웃해 주세요."
      data-screen-id="F1-PG-001"
      data-requirement-ids="F1-SE-01, F1-SE-11"
    >
      {/* 간격은 PatternFly Stack의 gutter를 쓴다. 화면마다 임의 여백 값을 만들지 않는다. */}
      <Stack hasGutter>
        {/*
          영역을 항상 렌더해두고 안쪽 내용만 바꾼다. aria-live 속성을 가진 요소 자체가 새로
          삽입되면 보조 기술이 놓치는 경우가 있어, 컨테이너를 고정하고 자식만 교체한다.
        */}
        <StackItem>
          <div aria-live="polite" aria-atomic="true">
            {unreachable != null && (
              <Alert variant="warning" isInline title="로그인 서버에 연결하지 못했습니다.">
                <p>{unreachable}</p>
                <Button variant="link" isInline onClick={() => void recheck()}>
                  다시 시도
                </Button>
              </Alert>
            )}
            {notice != null && <Alert variant="danger" isInline title={notice} />}
            {reason != null && unreachable == null && notice == null && (
              <ReasonAlert reason={reason} />
            )}
          </div>
        </StackItem>

        <LoginMethods
          developmentAuthEnabled={APP_ENV.authDevelopmentEnabled}
          isSubmitting={isSubmitting}
          onDevelopmentSession={() => void signInWithDevelopmentSession()}
        />
      </Stack>
    </LoginPage>
  );
}

/** 왜 로그인 화면에 와 있는지 알려준다. 첫 접속에는 아무 말도 하지 않는다. */
function ReasonAlert({ reason }: { reason: AnonymousReason }) {
  switch (reason) {
    case "expired":
      // F1-SE-11. 사용자는 방금까지 화면을 보고 있었으므로 왜 튕겼는지 알아야 한다.
      return (
        <Alert
          variant="warning"
          isInline
          title="세션이 만료되어 화면을 잠갔습니다. 다시 로그인해 주세요."
        />
      );
    case "signedOut":
      return <Alert variant="info" isInline title="로그아웃했습니다." />;
    case "initial":
      return null;
  }
}

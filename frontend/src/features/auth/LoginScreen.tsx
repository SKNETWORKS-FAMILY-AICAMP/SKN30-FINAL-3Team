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
 * 실제 진입 경로는 개발 세션 하나다. 계약이 확정되면 이 폼에 상태와 제출 핸들러만 붙이면 된다.
 */

import {
  ActionGroup,
  Alert,
  Button,
  Divider,
  Form,
  FormGroup,
  LoginPage,
  Stack,
  StackItem,
  TextInput,
} from "@patternfly/react-core";
import type { FormEvent } from "react";
import { useAuth } from "./AuthContext.tsx";
import type { AnonymousReason } from "./AuthContext.tsx";

const CREDENTIAL_HELP_ID = "login-credential-unavailable";

export function LoginScreen() {
  const { state, isSubmitting, notice, signInWithDevelopmentSession, recheck } = useAuth();
  const unreachable = state.status === "unreachable" ? state.message : null;
  const reason = state.status === "anonymous" ? state.reason : null;

  // 폼은 비활성이라 여기까지 오지 않지만, 브라우저 기본 제출로 화면이 새로 뜨는 일은 막는다.
  const blockSubmit = (event: FormEvent<HTMLFormElement>) => event.preventDefault();

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

        {/*
          비활성인 이유를 입력 앞에 둔다. 막힌 칸을 먼저 마주치고 나서 이유를 읽게 되면
          입력이 고장 난 것처럼 보인다. 보조 기술에는 aria-describedby로도 연결한다.
        */}
        <StackItem>
          <Alert
            id={CREDENTIAL_HELP_ID}
            variant="info"
            isInline
            title="아이디·비밀번호 로그인은 아직 제공하지 않습니다."
          >
            서버에 자격증명 검증 경로가 준비되면 이 입력이 열립니다. 그때까지는 아래 개발 세션으로
            접속해 주세요.
          </Alert>
        </StackItem>

        <StackItem>
          <Form onSubmit={blockSubmit}>
            <FormGroup label="아이디" fieldId="login-id" isRequired>
              <TextInput
                id="login-id"
                name="loginId"
                type="text"
                value=""
                onChange={() => undefined}
                autoComplete="username"
                isDisabled
                aria-describedby={CREDENTIAL_HELP_ID}
              />
            </FormGroup>
            <FormGroup label="비밀번호" fieldId="login-password" isRequired>
              <TextInput
                id="login-password"
                name="password"
                type="password"
                value=""
                onChange={() => undefined}
                autoComplete="current-password"
                isDisabled
                aria-describedby={CREDENTIAL_HELP_ID}
              />
            </FormGroup>
            <ActionGroup>
              <Button type="submit" variant="primary" isBlock isDisabled>
                로그인
              </Button>
            </ActionGroup>
          </Form>
        </StackItem>

        <StackItem>
          <Divider />
        </StackItem>

        <StackItem>
          <Button
            variant="secondary"
            isBlock
            isLoading={isSubmitting}
            isDisabled={isSubmitting}
            spinnerAriaValueText="로그인하는 중"
            onClick={() => void signInWithDevelopmentSession()}
          >
            개발용 세션으로 로그인
          </Button>
        </StackItem>
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

/**
 * 로그인 방식 표시 영역.
 *
 * 개발 세션 플래그는 버튼을 보여 주는 공개 빌드 설정일 뿐이다. 버튼을 숨겨도 자격증명 폼의
 * 향후 위치는 유지하고, 버튼을 보여 줘도 API 등록 여부는 Backend가 최종 통제한다.
 */

import {
  ActionGroup,
  Alert,
  Button,
  Divider,
  Form,
  FormGroup,
  StackItem,
  TextInput,
} from "@patternfly/react-core";
import type { FormEvent } from "react";

const CREDENTIAL_HELP_ID = "login-credential-unavailable";

interface LoginMethodsProps {
  readonly developmentAuthEnabled: boolean;
  readonly isSubmitting: boolean;
  readonly onDevelopmentSession: () => void;
}

export function LoginMethods({
  developmentAuthEnabled,
  isSubmitting,
  onDevelopmentSession,
}: LoginMethodsProps) {
  // 폼은 비활성이라 여기까지 오지 않지만, 브라우저 기본 제출로 화면이 새로 뜨는 일은 막는다.
  const blockSubmit = (event: FormEvent<HTMLFormElement>) => event.preventDefault();

  return (
    <>
      {/*
        비활성인 이유를 입력 앞에 둔다. 막힌 칸을 먼저 마주치고 나서 이유를 읽게 되면
        입력이 고장 난 것처럼 보인다. 보조 기술에는 aria-describedby로도 연결한다.
      */}
      <StackItem>
        <Alert
          id={CREDENTIAL_HELP_ID}
          variant="info"
          isInline
          title={
            developmentAuthEnabled
              ? "아이디·비밀번호 로그인은 아직 제공하지 않습니다."
              : "현재 사용할 수 있는 로그인 방식이 없습니다."
          }
        >
          {developmentAuthEnabled
            ? "서버에 자격증명 검증 경로가 준비되면 이 입력이 열립니다. 그때까지는 아래 개발 세션으로 접속해 주세요."
            : "아이디·비밀번호 로그인은 아직 제공되지 않으며, 이 환경의 개발용 세션 로그인도 비활성화되어 있습니다."}
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

      {developmentAuthEnabled && (
        <>
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
              onClick={onDevelopmentSession}
            >
              개발용 세션으로 로그인
            </Button>
          </StackItem>
        </>
      )}
    </>
  );
}

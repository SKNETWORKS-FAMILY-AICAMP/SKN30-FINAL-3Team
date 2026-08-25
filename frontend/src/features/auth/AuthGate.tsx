/**
 * 인증 게이트.
 *
 * 애플리케이션 본문과 로그인 화면 중 무엇을 그릴지만 정한다. 라우터를 쓰지 않는 이유는
 * 이 앱에 아직 라우팅 표준이 없고(설치된 라우터 없음), 인증 하나 때문에 라우팅 라이브러리와
 * URL 설계를 지금 확정하는 것이 이득보다 비용이 크기 때문이다. 로그인은 URL로 공유하거나
 * 뒤로 가기로 되돌아갈 대상도 아니다.
 */

import { Bullseye, Spinner } from "@patternfly/react-core";
import type { ReactNode } from "react";
import { isMockSource } from "../../config/env.ts";
import { useAuth } from "./AuthContext.tsx";
import { LoginScreen } from "./LoginScreen.tsx";

export function AuthGate({ children }: { children: ReactNode }) {
  const { state } = useAuth();

  // mock 데이터로 도는 동안은 서버도 세션도 없다. 여기서 막으면 백엔드 없이 화면을 보는
  // 경로 자체가 사라진다. AppShell의 `ledgerEnabled`가 쓰는 것과 같은 판단 기준이다.
  if (isMockSource()) return <>{children}</>;

  // 확인이 끝나기 전에는 아무 쪽도 그리지 않는다. 여기서 로그인 화면을 먼저 그리면
  // 이미 로그인한 사용자에게 새로고침마다 로그인 화면이 한 번 번쩍인다.
  if (state.status === "checking") {
    return (
      <Bullseye style={{ minHeight: "100vh" }}>
        <div role="status">
          <Spinner aria-label="세션을 확인하는 중입니다" />
        </div>
      </Bullseye>
    );
  }

  if (state.status === "authenticated") return <>{children}</>;

  return <LoginScreen />;
}

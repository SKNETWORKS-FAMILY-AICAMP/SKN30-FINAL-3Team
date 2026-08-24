import "./shell.css";
import { AppShell } from "./AppShell.jsx";
import { AuthGate, AuthProvider } from "./features/auth/index.ts";

/**
 * 애플리케이션 조합 지점.
 *
 * 인증 상태(AuthProvider)와 "무엇을 그릴지"(AuthGate)를 여기서만 엮는다. AppShell은 자기가
 * 로그인 화면 뒤에 있다는 사실을 알 필요가 없고, 게이트도 장부를 알 필요가 없다.
 */
export function App() {
  return (
    <AuthProvider>
      <AuthGate>
        <AppShell />
      </AuthGate>
    </AuthProvider>
  );
}

/**
 * 인증 상태의 소유자.
 *
 * 상태를 `user`, `loading`, `error` 세 값으로 늘어놓지 않고 하나의 판별 가능한 상태로 둔다.
 * 게이트가 구분해야 하는 것은 "아직 확인 안 함"과 "확인했더니 익명"이고, 독립 boolean으로는
 * 이 둘이 같은 조합(user=null, loading=false)으로 뭉개지거나 첫 렌더에서 로그인 화면이
 * 잠깐 번쩍이는 문제가 생긴다.
 *
 * 진행 중 여부(`isSubmitting`)만 따로 두는 이유는 이것이 상태와 직교하기 때문이다.
 * 로그인 중(익명 + 진행 중)과 로그아웃 중(인증됨 + 진행 중)이 모두 실제로 존재한다.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { isMockSource } from "../../config/env.ts";
import { clearCsrfToken } from "../../shared/api/index.ts";
import { createDevelopmentSession, deleteSession, fetchCurrentUser } from "./api/authApi.ts";
import { describeAuthError, isCanceled, isSessionLost } from "./model/authError.ts";
import type { AuthUser } from "./model/user.ts";

/** 왜 로그인 화면을 보고 있는지. 화면 문구가 달라진다. */
export type AnonymousReason =
  /** 아직 로그인한 적이 없다. */
  | "initial"
  /** 사용자가 직접 로그아웃했다. */
  | "signedOut"
  /** 세션이 끊겨 다시 잠겼다(F1-SE-11). */
  | "expired";

export type AuthState =
  /** `/auth/me` 확인 중. 이 동안에는 로그인 화면도 본문도 그리지 않는다. */
  | { readonly status: "checking" }
  | { readonly status: "anonymous"; readonly reason: AnonymousReason }
  | { readonly status: "authenticated"; readonly user: AuthUser }
  /** 인증 서버에 닿지 못했다. 자격증명 문제가 아니므로 재시도를 제공한다. */
  | { readonly status: "unreachable"; readonly message: string };

export interface AuthSession {
  readonly state: AuthState;
  /** 로그인 또는 로그아웃 요청이 진행 중인지. */
  readonly isSubmitting: boolean;
  /** 마지막 시도 실패 안내. 다음 시도를 시작하면 지운다. */
  readonly notice: string | null;
  readonly signInWithDevelopmentSession: () => Promise<void>;
  readonly signOut: () => Promise<void>;
  readonly recheck: () => Promise<void>;
  /**
   * 다른 기능이 401을 받았을 때 게이트를 다시 세운다.
   *
   * 사무소 공용 PC를 전제하므로(F1-SE-11) 세션이 끊긴 채 화면이 열려 있으면 안 된다.
   * 여기서 CSRF 원문도 함께 버려 끊긴 세션의 토큰이 남지 않게 한다.
   */
  readonly markSessionExpired: () => void;
}

const AuthContext = createContext<AuthSession | null>(null);

/**
 * mock 데이터로 도는 동안에는 인증 서버가 없다.
 *
 * `VITE_LEDGER_SOURCE=mock`은 이 프로젝트에서 "백엔드 없이 화면만 돌린다"는 뜻으로 이미 쓰이고
 * 있다(AppShell의 `ledgerEnabled`). 그 환경에서 `/auth/me`를 부르면 반드시 실패하고, 게이트가
 * 로그인 화면을 세우면 mock 데모 자체가 막힌다. 그래서 확인을 아예 시작하지 않는다.
 */
const SKIP_SESSION_CHECK = isMockSource();

const INITIAL_STATE: AuthState = SKIP_SESSION_CHECK
  ? { status: "anonymous", reason: "initial" }
  : { status: "checking" };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(INITIAL_STATE);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // 언마운트 뒤에 도착한 응답으로 상태를 건드리지 않기 위한 표시.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const applySessionLoss = useCallback((reason: AnonymousReason) => {
    clearCsrfToken();
    setState({ status: "anonymous", reason });
  }, []);

  /**
   * 세션 확인. 401은 오류가 아니라 "아직 로그인하지 않음"이라는 정상적인 결과다.
   * 그 외 실패는 자격증명 문제가 아니므로 재시도할 수 있는 상태로 남긴다.
   */
  const check = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const user = await fetchCurrentUser(signal);
        if (!mounted.current) return;
        setState({ status: "authenticated", user });
        setNotice(null);
      } catch (error) {
        if (!mounted.current || isCanceled(error)) return;
        if (isSessionLost(error)) {
          applySessionLoss("initial");
          return;
        }
        clearCsrfToken();
        setState({ status: "unreachable", message: describeAuthError(error) });
      }
    },
    [applySessionLoss],
  );

  useEffect(() => {
    if (SKIP_SESSION_CHECK) return;
    // StrictMode는 효과를 두 번 실행한다. 먼저 뜬 요청을 취소해 늦게 온 응답이 뒤엎지 않게 한다.
    const controller = new AbortController();
    void check(controller.signal);
    return () => controller.abort();
  }, [check]);

  const signInWithDevelopmentSession = useCallback(async () => {
    setIsSubmitting(true);
    setNotice(null);
    try {
      const user = await createDevelopmentSession();
      if (!mounted.current) return;
      setState({ status: "authenticated", user });
    } catch (error) {
      if (!mounted.current) return;
      // 실패해도 상태를 바꾸지 않는다. 사용자는 여전히 로그인 화면에 있고 안내만 필요하다.
      setNotice(describeAuthError(error));
    } finally {
      if (mounted.current) setIsSubmitting(false);
    }
  }, []);

  const signOut = useCallback(async () => {
    setIsSubmitting(true);
    setNotice(null);
    try {
      await deleteSession();
    } catch (error) {
      // 서버 폐기에 실패해도 이 브라우저는 반드시 잠근다. 공용 PC에서 로그아웃이
      // 조용히 실패하는 쪽이 훨씬 위험하다. 실패 사실만 다음 화면에 남긴다.
      if (mounted.current) setNotice(describeAuthError(error));
    } finally {
      if (!mounted.current) return;
      applySessionLoss("signedOut");
      setIsSubmitting(false);
    }
  }, [applySessionLoss]);

  const recheck = useCallback(async () => {
    setState({ status: "checking" });
    setNotice(null);
    await check();
  }, [check]);

  const markSessionExpired = useCallback(() => {
    applySessionLoss("expired");
  }, [applySessionLoss]);

  const value = useMemo<AuthSession>(
    () => ({
      state,
      isSubmitting,
      notice,
      signInWithDevelopmentSession,
      signOut,
      recheck,
      markSessionExpired,
    }),
    [state, isSubmitting, notice, signInWithDevelopmentSession, signOut, recheck, markSessionExpired],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthSession {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth는 AuthProvider 안에서만 쓸 수 있습니다.");
  }
  return value;
}

/** 현재 로그인한 사용자. 익명이면 null. 화면이 상태 분기를 반복하지 않게 하는 편의 함수다. */
export function currentUser(state: AuthState): AuthUser | null {
  return state.status === "authenticated" ? state.user : null;
}

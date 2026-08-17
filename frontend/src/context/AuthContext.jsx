import { createContext, useContext, useEffect, useState } from "react";
import {
  fetchCurrentUser,
  loginDevelopmentSession,
  logoutSession,
} from "../api/client.js";

const AuthContext = createContext({
  user: null,
  isAuthenticated: false,
  loading: true,
  error: null,
  loginDev: async () => {},
  logout: async () => {},
  checkAuth: async () => {},
});

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const checkAuth = async () => {
    setLoading(true);
    setError(null);
    try {
      const currentUser = await fetchCurrentUser();
      setUser(currentUser);
    } catch (err) {
      setUser(null);
      if (err.status !== 401 && err.status !== 403) {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const loginDev = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await loginDevelopmentSession();
      setUser(data.user);
      return data;
    } catch (err) {
      setError(err.message || "개발용 로그인에 실패했습니다.");
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    setLoading(true);
    try {
      await logoutSession();
      setUser(null);
    } catch (err) {
      setError(err.message || "로그아웃에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: Boolean(user),
        loading,
        error,
        loginDev,
        logout,
        checkAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

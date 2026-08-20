import "./shell.css";
import { AppShell } from "./AppShell.jsx";
import { AuthProvider } from "./context/AuthContext.jsx";

export function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}

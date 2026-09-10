import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app-entry.jsx";
import { RootErrorBoundary } from "./RootErrorBoundary.tsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);

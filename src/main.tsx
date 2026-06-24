import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { BackendProvider } from "./app/providers/BackendProvider";
import { ErrorBoundary } from "./components/system/ErrorBoundary";
import { installGlobalErrorHandlers } from "./services/errorLogger";
import "./styles/global.css";

installGlobalErrorHandlers();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BackendProvider>
        <App />
      </BackendProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);

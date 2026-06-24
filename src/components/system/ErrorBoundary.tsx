import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { logFrontendError } from "../../services/errorLogger";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logFrontendError("fatal", error.message, {
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="global-fallback">
          <AlertTriangle size={22} />
          <h1>Storage Insight ran into a UI error</h1>
          <p>Restart the application. The error was written to the frontend log.</p>
        </main>
      );
    }

    return this.props.children;
  }
}

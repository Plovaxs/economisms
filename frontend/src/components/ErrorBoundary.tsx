import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Changing this value (e.g. the current route path) clears a caught
   * error automatically, so navigating away from a crashed page recovers
   * without a full reload.
   */
  resetKey?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

// React has no hook equivalent for catching render-time exceptions --
// getDerivedStateFromError/componentDidCatch only exist on class
// components. Without this, any component throwing during render
// white-screens the entire app with no fallback at all.
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ErrorBoundary caught a render error:", error, info.componentStack);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }

    return (
      <div className="flex min-h-[60vh] items-center justify-center px-8">
        <div className="relative w-full max-w-lg rounded-2xl border border-white/10 bg-white/5 p-8 text-center shadow-glass backdrop-blur-xl before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px before:rounded-t-2xl before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-gradient-soft">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              className="h-6 w-6 text-accent-b"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a1.5 1.5 0 0 0 1.3 2.25h17.76a1.5 1.5 0 0 0 1.3-2.25L13.71 3.86a1.5 1.5 0 0 0-2.42 0Z"
              />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-slate-50">
            This page hit an unexpected error
          </h2>
          <p className="mt-2 font-mono text-xs text-slate-500">{error.message}</p>
          <p className="mt-3 text-sm text-slate-400">
            The rest of ECONOSIM is unaffected -- pick another page from the sidebar, or
            try this one again.
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="mt-6 rounded-lg bg-accent-gradient px-4 py-2 text-sm font-medium text-on-accent shadow-glow transition-opacity hover:opacity-90"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}

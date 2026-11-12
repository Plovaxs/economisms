import type { ReactNode } from "react";

import type { DataState } from "../hooks/useDashboardData";
import { LoadingPulse } from "./LoadingPulse";

interface DataStateViewProps<T> {
  state: DataState<T>;
  loadingLabel?: string;
  children: (data: T) => ReactNode;
}

export function DataStateView<T>({
  state,
  loadingLabel = "Loading real data...",
  children,
}: DataStateViewProps<T>) {
  if (state.phase === "loading") {
    return <LoadingPulse label={loadingLabel} />;
  }
  if (state.phase === "error") {
    return (
      <p className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
        {state.message}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

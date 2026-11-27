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
      <p className="rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-bad">
        {state.message}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

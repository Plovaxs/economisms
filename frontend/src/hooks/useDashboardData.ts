import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { getDashboardApi } from "../api/client";

export type DataState<T> =
  | { phase: "loading" }
  | { phase: "ready"; data: T }
  | { phase: "error"; message: string };

export function useDashboardData<T>(path: string, deps: readonly unknown[] = []): DataState<T> {
  const [state, setState] = useState<DataState<T>>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    getDashboardApi<T>(path)
      .then((data) => {
        if (!cancelled) setState({ phase: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            phase: "error",
            message: error instanceof ApiError ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

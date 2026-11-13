const TOKEN_KEY = "econosim.bearer_token";

// Dispatched whenever any API call comes back 401 -- a token that was
// valid when pasted stops working the moment either backend process is
// restarted (it provisions a fresh one), and there is no other signal
// the SPA gets for that. TokenGate listens for this to clear the stale
// token and re-prompt, instead of a page showing a raw error body.
export const UNAUTHORIZED_EVENT = "econosim:unauthorized";

// sessionStorage, not localStorage: this token unlocks real compute and
// real (if synthetic/demo) financial data, so it should not silently
// outlive the tab -- the same "don't persist what doesn't need to
// persist" instinct behind this project's own dashboard auth design.
export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  headers.set("Accept", "application/json");

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const raw = await response.text().catch(() => "");
    const message = extractErrorMessage(raw) || response.statusText;
    if (response.status === 401) {
      clearToken();
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

// Both backends report errors as JSON, but in two different shapes --
// the dashboard's is a flat `{"error": "<message>"}`, the job API's is
// `{"error": {"code", "message", ...}}`. Falls back to the raw text for
// anything else so a real error is never silently swallowed.
function extractErrorMessage(raw: string): string | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { error?: unknown };
    if (typeof parsed.error === "string") return parsed.error;
    if (
      parsed.error &&
      typeof parsed.error === "object" &&
      typeof (parsed.error as { message?: unknown }).message === "string"
    ) {
      return (parsed.error as { message: string }).message;
    }
  } catch {
    // not JSON -- fall through to the raw body below
  }
  return raw;
}

export function getJobsApi<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`/api/jobs${path}`, init);
}

export function getDashboardApi<T>(path: string, init?: RequestInit): Promise<T> {
  const separator = path.includes("?") ? "&" : "?";
  return request<T>(`/api/dashboard${path}${separator}format=json`, init);
}

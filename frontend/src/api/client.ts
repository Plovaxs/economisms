const TOKEN_KEY = "econosim.bearer_token";

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
    const body = await response.text().catch(() => "");
    throw new ApiError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

export function getJobsApi<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(`/api/jobs${path}`, init);
}

export function getDashboardApi<T>(path: string, init?: RequestInit): Promise<T> {
  const separator = path.includes("?") ? "&" : "?";
  return request<T>(`/api/dashboard${path}${separator}format=json`, init);
}

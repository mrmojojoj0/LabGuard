import type { ApiErrorShape } from "./types";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
let csrfToken: string | null = sessionStorage.getItem("labguard_csrf");
export const setCsrfToken = (token: string | null) => {
  csrfToken = token;
  if (token) sessionStorage.setItem("labguard_csrf", token);
  else sessionStorage.removeItem("labguard_csrf");
};
export const getCsrfToken = () => csrfToken;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  if (
    csrfToken &&
    init.method &&
    !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())
  )
    headers.set("X-CSRF-Token", csrfToken);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/v1${path}`, {
      ...init,
      headers,
      credentials: "include",
    });
  } catch {
    throw new ApiError(
      "Could not reach the LabGuard server.",
      0,
      "network_error",
    );
  }
  if (!response.ok) {
    let data: ApiErrorShape = {};
    try {
      data = (await response.json()) as ApiErrorShape;
    } catch {
      /* empty/non-JSON error */
    }
    const detail =
      data.error ?? (typeof data.detail === "object" ? data.detail : undefined);
    const message =
      detail?.message ??
      (typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`);
    throw new ApiError(message, response.status, detail?.code, detail?.details);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const json = (method: string, value?: unknown): RequestInit => ({
  method,
  ...(value === undefined ? {} : { body: JSON.stringify(value) }),
});

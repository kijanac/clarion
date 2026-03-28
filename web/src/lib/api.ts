const BASE = "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, userMessage: string, detail: string) {
    super(userMessage);
    this.status = status;
    if (detail) {
      console.error(`API ${status}: ${detail}`);
    }
  }
}

function friendlyMessage(status: number): string {
  if (status === 404) return "We couldn't find this agent. It may have been removed.";
  if (status === 409) return "An agent with this name already exists. Try a different name.";
  if (status === 503) return "Running agents isn't available in this mode. Ask your admin to enable it.";
  if (status >= 500) return "Something went wrong. Try refreshing the page, or contact your admin for help.";
  if (status === 400) return "Invalid input. Please check the form and try again.";
  return "Something went wrong. Try again.";
}

async function apiRequest<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't connect to the server. Check your internet connection or try again in a moment.", "Network error");
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "" }));
    const detail = err.detail || res.statusText;

    // For 400 validation errors, show the server's detail (it's user-facing validation text)
    if (res.status === 400 && detail) {
      throw new ApiError(res.status, detail, detail);
    }

    throw new ApiError(res.status, friendlyMessage(res.status), detail);
  }

  return res.json();
}

export function apiFetch<T>(path: string): Promise<T> {
  return apiRequest<T>("GET", path);
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>("POST", path, body);
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>("PUT", path, body);
}

export function apiDelete<T>(path: string): Promise<T> {
  return apiRequest<T>("DELETE", path);
}

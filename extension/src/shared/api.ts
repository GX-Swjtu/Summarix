import type { Artifact, ConversationDetail, HistoryPage, ModelSettings, PageContext, User } from "./types";

const API_BASE_KEY = "summarix_api_base";
const USER_CACHE_KEY = "summarix_user";

class ResponseError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ResponseError";
    this.status = status;
  }
}

export async function getApiBase(): Promise<string> {
  const stored = await chrome.storage.local.get(API_BASE_KEY);
  return stored[API_BASE_KEY] || "http://127.0.0.1:8000";
}

export async function setApiBase(value: string): Promise<void> {
  await chrome.storage.local.set({ [API_BASE_KEY]: value.replace(/\/$/, "") });
}

async function fetchApiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const apiBase = await getApiBase();
  return fetch(`${apiBase}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init.headers || {})
    }
  });
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => ({ detail: fallback }));
    return payload.detail || fallback;
  }
  const text = await response.text().catch(() => "");
  return text || fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetchApiResponse(path, init);
  if (!response.ok) {
    throw new ResponseError(response.status, await readErrorDetail(response, response.statusText || "请求失败"));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

async function fetchStreamResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetchApiResponse(path, init);
  if (response.status !== 401) {
    return response;
  }
  const refreshedUser = await refreshSession();
  if (!refreshedUser) {
    return response;
  }
  await response.body?.cancel();
  return fetchApiResponse(path, init);
}

export function readCachedUser(): User | null {
  const raw = sessionStorage.getItem(USER_CACHE_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

function cacheUser(user: User | null): void {
  if (user) {
    sessionStorage.setItem(USER_CACHE_KEY, JSON.stringify(user));
  } else {
    sessionStorage.removeItem(USER_CACHE_KEY);
  }
}

export async function register(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
  cacheUser(response.user);
  return response.user;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
  cacheUser(response.user);
  return response.user;
}

export async function refreshSession(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/refresh", { method: "POST" });
    cacheUser(response.user);
    return response.user;
  } catch {
    cacheUser(null);
    return null;
  }
}

export async function getMe(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/me");
    cacheUser(response.user);
    return response.user;
  } catch (error) {
    if (error instanceof ResponseError && error.status === 401) {
      return refreshSession();
    }
    cacheUser(null);
    return null;
  }
}

export async function logout(): Promise<void> {
  await request<void>("/api/auth/logout", { method: "POST" });
  cacheUser(null);
}

export async function uploadArtifact(dataUrl: string, filename = "screenshot.png"): Promise<Artifact> {
  const response = await fetch(dataUrl);
  const blob = await response.blob();
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("source", "screenshot");
  return request<Artifact>("/api/chat/artifacts", { method: "POST", body: form });
}

export async function listHistory(offset = 0, limit = 20): Promise<HistoryPage> {
  return request<HistoryPage>(`/api/history?offset=${offset}&limit=${limit}`);
}

export async function getHistoryDetail(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/history/${id}`);
}

export async function getModelSettings(): Promise<ModelSettings> {
  return request<ModelSettings>("/api/settings/models");
}

export async function updateModelSettings(payload: Partial<ModelSettings>): Promise<ModelSettings> {
  return request<ModelSettings>("/api/settings/models", {
    method: "PUT",
    body: JSON.stringify({
      text_summary_model: payload.text_summary_model || null,
      vision_analysis_model: payload.vision_analysis_model || null,
      conversation_model: payload.conversation_model || null
    })
  });
}

export async function streamChat(options: {
  conversationId?: string | null;
  message: string;
  context?: PageContext | null;
  artifactIds?: string[];
  onConversation: (id: string) => void;
  onDelta: (text: string) => void;
}): Promise<void> {
  const response = await fetchStreamResponse("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: options.conversationId || null,
      message: options.message,
      context: options.context || null,
      artifact_ids: options.artifactIds || []
    })
  });
  if (!response.ok) {
    throw new ResponseError(response.status, await readErrorDetail(response, response.statusText || "流式请求失败"));
  }
  if (!response.body) {
    throw new Error("流式响应为空");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const eventText of events) {
      const lines = eventText.split("\n");
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (event === "conversation") options.onConversation(data);
      if (event === "delta") options.onDelta(data);
      if (event === "error") {
        await reader.cancel();
        throw new Error(data || "AI 响应失败");
      }
    }
  }
}

import type { AdkEvent, Artifact, ConversationDetail, HistoryPage, ModelSettings, PageContext, User } from "./types";

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

export async function readCachedUser(): Promise<User | null> {
  const stored = await chrome.storage.local.get(USER_CACHE_KEY);
  return (stored[USER_CACHE_KEY] as User | undefined) || null;
}

async function cacheUser(user: User | null): Promise<void> {
  if (user) {
    await chrome.storage.local.set({ [USER_CACHE_KEY]: user });
  } else {
    await chrome.storage.local.remove(USER_CACHE_KEY);
  }
}

export async function register(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
  await cacheUser(response.user);
  return response.user;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
  await cacheUser(response.user);
  return response.user;
}

export async function refreshSession(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/refresh", { method: "POST" });
    await cacheUser(response.user);
    return response.user;
  } catch {
    await cacheUser(null);
    return null;
  }
}

export async function getMe(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/me");
    await cacheUser(response.user);
    return response.user;
  } catch (error) {
    if (error instanceof ResponseError && error.status === 401) {
      return refreshSession();
    }
    await cacheUser(null);
    return null;
  }
}

export async function logout(): Promise<void> {
  await request<void>("/api/auth/logout", { method: "POST" });
  await cacheUser(null);
}

export async function uploadArtifact(file: Blob, filename = "image.png", source: "screenshot" | "upload" = "upload"): Promise<Artifact> {
  const form = new FormData();
  form.append("file", file, filename);
  form.append("source", source);
  return request<Artifact>("/api/chat/artifacts", { method: "POST", body: form });
}

export async function getArtifactObjectUrl(id: string): Promise<string> {
  const response = await fetchApiResponse(`/api/chat/artifacts/${id}/content`);
  if (!response.ok) {
    throw new ResponseError(response.status, await readErrorDetail(response, response.statusText || "读取附件失败"));
  }
  return URL.createObjectURL(await response.blob());
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
  signal?: AbortSignal;
  onConversation: (payload: { id: string; user_message_id?: string }) => void;
  onAdkEvent: (event: AdkEvent) => void;
  onPersisted?: (payload: { assistant_message_id?: string }) => void;
}): Promise<void> {
  const response = await fetchStreamResponse("/api/chat/stream", {
    method: "POST",
    signal: options.signal,
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

  const consumeEventText = async (eventText: string): Promise<void> => {
    if (!eventText.trim()) {
      return;
    }
    const lines = eventText.split(/\r?\n/);
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");

    if (event === "conversation") {
      const payload = JSON.parse(data) as { id: string; user_message_id?: string };
      options.onConversation(payload);
    }
    if (event === "adk_event") options.onAdkEvent(JSON.parse(data) as AdkEvent);
    if (event === "persisted") options.onPersisted?.(JSON.parse(data) as { assistant_message_id?: string });
    if (event === "error") {
      await reader.cancel();
      throw new Error(data || "AI 响应失败");
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() || "";
    for (const eventText of events) {
      await consumeEventText(eventText);
    }
    if (done) {
      break;
    }
  }

  await consumeEventText(buffer);
}

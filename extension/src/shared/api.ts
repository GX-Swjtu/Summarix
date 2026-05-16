import type {
  AdkEvent,
  Artifact,
  ConversationDetail,
  HistoryPage,
  ModelSettings,
  PageContext,
  SuggestedQuestionsPayload,
  User
} from "./types";

const API_BASE_KEY = "summarix_api_base";
const USER_CACHE_KEY = "summarix_user";

type RequestOptions = {
  retryAuth?: boolean;
};

export class ResponseError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ResponseError";
    this.status = status;
  }
}

export class BackendUnavailableError extends Error {
  constructor() {
    super("后端暂时不可访问，请稍后重试。");
    this.name = "BackendUnavailableError";
  }
}

export function isAuthRequiredError(error: unknown): boolean {
  return error instanceof ResponseError && error.status === 401;
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
  try {
    return await fetch(`${apiBase}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(init.headers || {})
      }
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new BackendUnavailableError();
  }
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

async function request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const retryAuth = options.retryAuth ?? true;
  let response = await fetchApiResponse(path, init);
  if (response.status === 401 && retryAuth) {
    const refreshedUser = await refreshSession();
    if (refreshedUser) {
      await response.body?.cancel().catch(() => undefined);
      response = await fetchApiResponse(path, init);
    }
  }
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

export async function clearCachedUser(): Promise<void> {
  await cacheUser(null);
}

export async function register(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>(
    "/api/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ email, password })
    },
    { retryAuth: false }
  );
  await cacheUser(response.user);
  return response.user;
}

export async function login(email: string, password: string): Promise<User> {
  const response = await request<{ user: User }>(
    "/api/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password })
    },
    { retryAuth: false }
  );
  await cacheUser(response.user);
  return response.user;
}

export async function refreshSession(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/refresh", { method: "POST" }, { retryAuth: false });
    await cacheUser(response.user);
    return response.user;
  } catch (error) {
    if (isAuthRequiredError(error)) {
      await cacheUser(null);
      return null;
    }
    throw error;
  }
}

export async function getMe(): Promise<User | null> {
  try {
    const response = await request<{ user: User }>("/api/auth/me");
    await cacheUser(response.user);
    return response.user;
  } catch (error) {
    if (isAuthRequiredError(error)) {
      await cacheUser(null);
      return null;
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  try {
    await request<void>("/api/auth/logout", { method: "POST" }, { retryAuth: false });
  } finally {
    await cacheUser(null);
  }
}

export async function uploadArtifact(file: Blob, filename = "image.png", source: "screenshot" | "upload" = "upload"): Promise<Artifact> {
  const form = new FormData();
  form.append("file", file, filename);
  form.append("source", source);
  return request<Artifact>("/api/chat/artifacts", { method: "POST", body: form });
}

export async function getArtifactObjectUrl(id: string): Promise<string> {
  const response = await fetchStreamResponse(`/api/chat/artifacts/${id}/content`);
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
      theme: payload.theme ?? "default",
      text_summary_model: payload.text_summary_model?.trim() || null,
      conversation_model: payload.conversation_model?.trim() || null,
      xiaohongshu_model: payload.xiaohongshu_model?.trim() || null,
      short_video_script_model: payload.short_video_script_model?.trim() || null,
      suggested_questions_model: payload.suggested_questions_model?.trim() || null,
      text_summary_thinking_mode: payload.text_summary_thinking_mode ?? "default",
      conversation_thinking_mode: payload.conversation_thinking_mode ?? "default",
      xiaohongshu_thinking_mode: payload.xiaohongshu_thinking_mode ?? "default",
      short_video_script_thinking_mode: payload.short_video_script_thinking_mode ?? "default",
      suggested_questions_thinking_mode: payload.suggested_questions_thinking_mode ?? "disabled"
    })
  });
}

async function consumeSseResponse(response: Response, onEvent: (event: string | undefined, data: string) => Promise<void> | void): Promise<void> {
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
    if (!eventText.trim()) return;
    const lines = eventText.split(/\r?\n/);
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    try {
      await onEvent(event, data);
    } catch (error) {
      await reader.cancel().catch(() => undefined);
      throw error;
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
    if (done) break;
  }

  await consumeEventText(buffer);
}

export async function streamChat(options: {
  conversationId?: string | null;
  message: string;
  context?: PageContext | null;
  artifactIds?: string[];
  signal?: AbortSignal;
  suggestedQuestions?: boolean;
  onConversation: (payload: { id: string; user_message_id?: string; reference_artifacts?: Artifact[] }) => void;
  onAdkEvent: (event: AdkEvent) => void;
  onPersisted?: (payload: { assistant_message_id?: string }) => void;
  onDone?: () => void;
  onSuggestedQuestions?: (payload: SuggestedQuestionsPayload) => void;
}): Promise<void> {
  const response = await fetchStreamResponse("/api/chat/stream", {
    method: "POST",
    signal: options.signal,
    body: JSON.stringify({
      conversation_id: options.conversationId || null,
      message: options.message,
      context: options.context || null,
      artifact_ids: options.artifactIds || [],
      suggested_questions: options.suggestedQuestions ?? true
    })
  });

  await consumeSseResponse(response, async (event, data) => {
    if (event === "conversation") {
      const payload = JSON.parse(data) as { id: string; user_message_id?: string; reference_artifacts?: Artifact[] };
      options.onConversation(payload);
    }
    if (event === "adk_event") options.onAdkEvent(JSON.parse(data) as AdkEvent);
    if (event === "persisted") options.onPersisted?.(JSON.parse(data) as { assistant_message_id?: string });
    if (event === "done") options.onDone?.();
    if (event === "suggested_questions") options.onSuggestedQuestions?.(JSON.parse(data) as SuggestedQuestionsPayload);
    if (event === "error") throw new Error(data || "AI 响应失败");
  });
}

export async function streamSuggestedQuestions(options: {
  conversationId: string;
  assistantMessageId?: string | null;
  count?: number;
  signal?: AbortSignal;
  onSuggestedQuestions: (payload: SuggestedQuestionsPayload) => void;
}): Promise<void> {
  const response = await fetchStreamResponse("/api/chat/suggestions/stream", {
    method: "POST",
    signal: options.signal,
    body: JSON.stringify({
      conversation_id: options.conversationId,
      assistant_message_id: options.assistantMessageId || null,
      count: options.count || 3
    })
  });

  await consumeSseResponse(response, async (event, data) => {
    if (event === "suggested_questions") options.onSuggestedQuestions(JSON.parse(data) as SuggestedQuestionsPayload);
    if (event === "error") throw new Error(data || "建议问题生成失败");
  });
}

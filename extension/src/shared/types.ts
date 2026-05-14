export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type PageContext = {
  page_url?: string | null;
  page_title?: string | null;
  page_text?: string | null;
};

export type Artifact = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  source?: "screenshot" | "page_text" | "selection" | "upload" | string;
  page_url?: string | null;
  page_title?: string | null;
  text_excerpt?: string | null;
  text_length?: number | null;
  content_hash?: string | null;
  adk_invocation_id?: string | null;
};

export type MessageAttachment = Artifact & {
  previewUrl?: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  adk_invocation_id?: string | null;
  created_at: string;
  artifacts?: Artifact[];
};

export type ConversationSummary = {
  id: string;
  title: string;
  page_url?: string | null;
  page_title?: string | null;
  updated_at: string;
};

export type HistoryPage = {
  items: ConversationSummary[];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type ConversationDetail = ConversationSummary & {
  messages: Message[];
  artifacts: Artifact[];
};

export type AdkPart = {
  text?: string;
  thought?: boolean;
  functionCall?: unknown;
  function_call?: unknown;
  functionResponse?: unknown;
  function_response?: unknown;
};

export type AdkEvent = {
  id?: string;
  author?: string;
  invocationId?: string;
  invocation_id?: string;
  content?: {
    role?: string;
    parts?: AdkPart[];
  };
  partial?: boolean;
  turnComplete?: boolean;
  turn_complete?: boolean;
  interrupted?: boolean;
  errorCode?: string;
  error_code?: string;
  errorMessage?: string;
  error_message?: string;
};

export type ThinkingMode = "default" | "enabled" | "disabled";

export type SuggestedQuestionsPayload = {
  questions: string[];
};

export type ModelSettings = {
  text_summary_model?: string | null;
  conversation_model?: string | null;
  xiaohongshu_model?: string | null;
  short_video_script_model?: string | null;
  suggested_questions_model?: string | null;
  text_summary_thinking_mode: ThinkingMode;
  conversation_thinking_mode: ThinkingMode;
  xiaohongshu_thinking_mode: ThinkingMode;
  short_video_script_thinking_mode: ThinkingMode;
  suggested_questions_thinking_mode: ThinkingMode;
  defaults: Record<string, string>;
};

export type ExtractedPage = {
  title: string;
  url: string;
  text: string;
};

export type ActiveTabInfo = {
  id?: number;
  title?: string;
  url?: string;
};

export type BackgroundRequest =
  | { type: "capture-visible-tab" }
  | { type: "extract-page" }
  | { type: "get-active-tab" };

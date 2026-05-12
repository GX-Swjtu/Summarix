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
};

export type Message = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
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

export type ModelSettings = {
  text_summary_model?: string | null;
  vision_analysis_model?: string | null;
  conversation_model?: string | null;
  defaults: Record<string, string>;
};

export type ExtractedPage = {
  title: string;
  url: string;
  text: string;
};

export type BackgroundRequest =
  | { type: "capture-visible-tab" }
  | { type: "extract-page" };

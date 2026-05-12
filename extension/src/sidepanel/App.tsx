import { Camera, ChevronDown, ChevronRight, FileText, History, ImagePlus, Loader2, LogIn, LogOut, MessageSquare, RefreshCw, Save, Send, Settings, X } from "lucide-react";
import { type ClipboardEvent, type DragEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  getApiBase,
  getArtifactObjectUrl,
  getHistoryDetail,
  getMe,
  getModelSettings,
  listHistory,
  login,
  logout,
  readCachedUser,
  register,
  setApiBase,
  streamChat,
  updateModelSettings,
  uploadArtifact
} from "../shared/api";
import type { AdkEvent, Artifact, ConversationDetail, ConversationSummary, ExtractedPage, MessageAttachment, ModelSettings, User } from "../shared/types";
import { captureVisibleTab, extractCurrentPage } from "./chrome";

type View = "chat" | "history" | "settings";

type LocalMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  thought?: string;
  thoughtOpen?: boolean;
  artifacts?: MessageAttachment[];
};

type DraftAttachment = {
  id: string;
  file: File;
  filename: string;
  source: "screenshot" | "upload";
  previewUrl: string;
  uploading: boolean;
  error?: string | null;
};

const HISTORY_PAGE_SIZE = 20;

function makeLocalId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function mergeCompleteText(current: string, incoming: string): string {
  if (!current || incoming.startsWith(current)) return incoming;
  if (current.startsWith(incoming)) return current;
  return current + incoming;
}

function getTurnComplete(event: AdkEvent): boolean {
  return event.turnComplete === true || event.turn_complete === true;
}

function getEventError(event: AdkEvent): string | null {
  return event.errorMessage || event.error_message || event.errorCode || event.error_code || null;
}

function getEventText(event: AdkEvent, thought: boolean): string {
  return (event.content?.parts || [])
    .filter((part) => Boolean(part.text) && Boolean(part.thought) === thought)
    .map((part) => part.text || "")
    .join("");
}

function appendEventText(current: string, incoming: string, partial: boolean): string {
  return partial ? current + incoming : mergeCompleteText(current, incoming);
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [view, setView] = useState<View>("chat");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      const cachedUser = await readCachedUser();
      if (active && cachedUser) setUser(cachedUser);
      const restoredUser = await getMe();
      if (!active) return;
      setUser(restoredUser);
      setBootstrapping(false);
    }
    restoreSession().catch(() => {
      if (active) setBootstrapping(false);
    });
    return () => {
      active = false;
    };
  }, []);

  if (bootstrapping) {
    return <LoadingScreen />;
  }

  if (!user) {
    return <AuthScreen onAuthed={setUser} error={error} setError={setError} />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <strong>Summarix</strong>
          <span>{user.email}</span>
        </div>
        <button
          className="icon-button"
          title="退出登录"
          onClick={async () => {
            setBusy(true);
            await logout().finally(() => setBusy(false));
            setUser(null);
          }}
          disabled={busy}
        >
          <LogOut size={18} />
        </button>
      </header>

      <nav className="tabs" aria-label="主导航">
        <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}><MessageSquare size={16} />聊天</button>
        <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}><History size={16} />历史</button>
        <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}><Settings size={16} />设置</button>
      </nav>

      {error && <div className="notice">{error}</div>}
      <main className="main-panel">
        {view === "chat" && <ChatView setError={setError} />}
        {view === "history" && <HistoryView setError={setError} />}
        {view === "settings" && <SettingsView setError={setError} />}
      </main>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="auth-shell loading-shell">
      <div className="brand-row"><MessageSquare size={24} /><strong>Summarix</strong></div>
      <Loader2 className="spin" size={22} />
    </div>
  );
}

function AuthScreen(props: { onAuthed: (user: User) => void; error: string | null; setError: (value: string | null) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    props.setError(null);
    setLoading(true);
    try {
      const nextUser = mode === "login" ? await login(email, password) : await register(email, password);
      props.onAuthed(nextUser);
    } catch (error) {
      props.setError(error instanceof Error ? error.message : "认证失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="brand-row">
        <MessageSquare size={24} />
        <strong>Summarix</strong>
      </div>
      <form className="auth-form" onSubmit={submit}>
        <label>
          邮箱
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
        </label>
        {props.error && <div className="notice">{props.error}</div>}
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <LogIn size={16} />}
          {mode === "login" ? "登录" : "注册"}
        </button>
        <div className="auth-actions">
          <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "创建账号" : "返回登录"}
          </button>
          <button
            type="button"
            onClick={async () => {
              setLoading(true);
              props.setError(null);
              const restored = await getMe().finally(() => setLoading(false));
              if (restored) props.onAuthed(restored);
            }}
          >
            恢复会话
          </button>
        </div>
      </form>
    </div>
  );
}

function ChatView({ setError }: { setError: (value: string | null) => void }) {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [page, setPage] = useState<ExtractedPage | null>(null);
  const [drafts, setDrafts] = useState<DraftAttachment[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const pageStatus = useMemo(() => {
    if (!page) return "未提取正文";
    return `${page.title || "当前网页"} · ${Math.round(page.text.length / 100) / 10}k 字`;
  }, [page]);

  function addAttachmentFiles(files: Iterable<File>, source: "screenshot" | "upload") {
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length === 0) {
      setError("请选择图片文件");
      return;
    }
    setError(null);
    setDrafts((items) => [
      ...items,
      ...imageFiles.map((file) => ({
        id: makeLocalId(),
        file,
        filename: file.name || "image.png",
        source,
        previewUrl: URL.createObjectURL(file),
        uploading: false,
        error: null
      }))
    ]);
  }

  function removeDraft(id: string) {
    setDrafts((items) => {
      const target = items.find((item) => item.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return items.filter((item) => item.id !== id);
    });
  }

  async function extractPage() {
    setError(null);
    setLoading(true);
    try {
      setPage(await extractCurrentPage());
    } catch (error) {
      setError(error instanceof Error ? error.message : "提取网页失败");
    } finally {
      setLoading(false);
    }
  }

  async function captureAndInsert() {
    setError(null);
    setLoading(true);
    try {
      const dataUrl = await captureVisibleTab();
      const blob = await (await fetch(dataUrl)).blob();
      const file = new File([blob], `screenshot-${Date.now()}.png`, { type: blob.type || "image/png" });
      addAttachmentFiles([file], "screenshot");
    } catch (error) {
      setError(error instanceof Error ? error.message : "截图失败");
    } finally {
      setLoading(false);
    }
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
    if (files.length > 0) {
      event.preventDefault();
      addAttachmentFiles(files, "upload");
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragActive(false);
    addAttachmentFiles(Array.from(event.dataTransfer.files), "upload");
  }

  async function uploadDrafts(): Promise<MessageAttachment[]> {
    if (drafts.length === 0) return [];
    setDrafts((items) => items.map((item) => ({ ...item, uploading: true, error: null })));
    const uploaded: MessageAttachment[] = [];
    for (const draft of drafts) {
      try {
        const artifact = await uploadArtifact(draft.file, draft.filename, draft.source);
        uploaded.push({ ...artifact, previewUrl: draft.previewUrl });
      } catch (error) {
        setDrafts((items) => items.map((item) => (item.id === draft.id ? { ...item, uploading: false, error: error instanceof Error ? error.message : "上传失败" } : item)));
        throw error;
      }
    }
    return uploaded;
  }

  function toggleThought(id: string) {
    setMessages((items) => items.map((item) => (item.id === id ? { ...item, thoughtOpen: !item.thoughtOpen } : item)));
  }

  function applyAdkEvent(assistantId: string, event: AdkEvent) {
    const errorMessage = getEventError(event);
    if (errorMessage) setError(errorMessage);
    if (event.interrupted) return;
    const answerText = getEventText(event, false);
    const thoughtText = getEventText(event, true);
    const turnComplete = getTurnComplete(event);
    const isPartial = event.partial === true;
    if (!answerText && !thoughtText && !turnComplete) return;
    setMessages((items) => items.map((item) => {
      if (item.id !== assistantId) return item;
      const next = { ...item };
      if (answerText) {
        next.content = appendEventText(next.content, answerText, isPartial);
      }
      if (thoughtText) {
        next.thought = appendEventText(next.thought || "", thoughtText, isPartial);
      }
      if (!next.content.trim() && turnComplete && next.thought?.trim()) {
        next.content = next.thought;
        next.thought = undefined;
        next.thoughtOpen = false;
      }
      return next;
    }));
  }

  async function sendMessage() {
    if (!input.trim() || loading) return;
    setError(null);
    setLoading(true);
    const messageText = input.trim();
    try {
      const uploadedArtifacts = await uploadDrafts();
      const userMessage: LocalMessage = { id: makeLocalId(), role: "user", content: messageText, artifacts: uploadedArtifacts };
      const assistantId = makeLocalId();
      setMessages((items) => [...items, userMessage, { id: assistantId, role: "assistant", content: "" }]);
      setInput("");
      setDrafts([]);
      await streamChat({
        conversationId,
        message: messageText,
        context: page ? { page_url: page.url, page_title: page.title, page_text: page.text } : null,
        artifactIds: uploadedArtifacts.map((artifact) => artifact.id),
        onConversation: (payload) => setConversationId(payload.id),
        onAdkEvent: (event) => applyAdkEvent(assistantId, event)
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : "发送失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section
      className={`chat-layout${dragActive ? " drag-active" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
    >
      <div className="tool-row">
        <button title="提取正文" onClick={extractPage} disabled={loading}><FileText size={16} />正文</button>
        <button title="截图插入" onClick={captureAndInsert} disabled={loading}><Camera size={16} />截图</button>
        <span className="status-text">{pageStatus}</span>
      </div>

      <div className="message-list">
        {messages.length === 0 && <div className="empty-state">打开网页后提取正文或插入图片，然后直接提问。</div>}
        {messages.map((message) => <MessageBubble key={message.id} message={message} onToggleThought={toggleThought} />)}
      </div>

      {drafts.length > 0 && <DraftStrip drafts={drafts} onRemove={removeDraft} />}

      <div className="composer">
        <input
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          title="选择图片"
          aria-label="选择图片"
          accept="image/*"
          multiple
          onChange={(event) => {
            if (event.target.files) addAttachmentFiles(Array.from(event.target.files), "upload");
            event.target.value = "";
          }}
        />
        <button className="icon-button attach" title="插入图片" onClick={() => fileInputRef.current?.click()} disabled={loading}>
          <ImagePlus size={18} />
        </button>
        <textarea value={input} onPaste={handlePaste} onChange={(event) => setInput(event.target.value)} placeholder="输入问题" rows={3} />
        <button className="icon-button send" title="发送" onClick={sendMessage} disabled={loading || !input.trim()}>
          {loading ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
        </button>
      </div>
    </section>
  );
}

function DraftStrip({ drafts, onRemove }: { drafts: DraftAttachment[]; onRemove: (id: string) => void }) {
  return (
    <div className="draft-strip">
      {drafts.map((draft) => (
        <figure className={`image-chip${draft.error ? " error" : ""}`} key={draft.id}>
          <img src={draft.previewUrl} alt={draft.filename} />
          <figcaption>{draft.uploading ? "上传中" : draft.filename}</figcaption>
          <button title="删除图片" onClick={() => onRemove(draft.id)} disabled={draft.uploading}><X size={14} /></button>
        </figure>
      ))}
    </div>
  );
}

function MessageBubble({ message, onToggleThought }: { message: LocalMessage; onToggleThought?: (id: string) => void }) {
  const hasThought = Boolean(message.thought?.trim());
  return (
    <article className={`message ${message.role}`}>
      {message.artifacts && message.artifacts.length > 0 && (
        <div className="message-attachments">
          {message.artifacts.map((artifact) => <AttachmentPreview artifact={artifact} key={artifact.id} />)}
        </div>
      )}
      <div className="message-text">{message.content || (message.role === "assistant" ? "..." : "")}</div>
      {hasThought && message.role === "assistant" && (
        <div className="thought-block">
          <button type="button" className="thought-toggle" onClick={() => onToggleThought?.(message.id)}>
            {message.thoughtOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            思考
          </button>
          {message.thoughtOpen && <div className="thought-content">{message.thought}</div>}
        </div>
      )}
    </article>
  );
}

function AttachmentPreview({ artifact }: { artifact: MessageAttachment | Artifact }) {
  const [url, setUrl] = useState("previewUrl" in artifact && artifact.previewUrl ? artifact.previewUrl : "");

  useEffect(() => {
    if ("previewUrl" in artifact && artifact.previewUrl) {
      setUrl(artifact.previewUrl);
      return;
    }
    let objectUrl = "";
    let active = true;
    getArtifactObjectUrl(artifact.id)
      .then((nextUrl) => {
        objectUrl = nextUrl;
        if (active) setUrl(nextUrl);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifact]);

  return (
    <figure className="attachment-preview">
      {url ? <img src={url} alt={artifact.filename} /> : <div className="image-placeholder" />}
      <figcaption>{artifact.filename}</figcaption>
    </figure>
  );
}

function HistoryView({ setError }: { setError: (value: string | null) => void }) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);

  async function load(nextOffset = 0, append = false) {
    setLoading(true);
    setError(null);
    try {
      const page = await listHistory(nextOffset, HISTORY_PAGE_SIZE);
      setItems((current) => (append ? [...current, ...page.items] : page.items));
      setOffset(page.offset + page.items.length);
      setHasMore(page.has_more);
      if (!append) setDetail(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "加载历史失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function openDetail(id: string) {
    setError(null);
    try {
      setDetail(await getHistoryDetail(id));
    } catch (error) {
      setError(error instanceof Error ? error.message : "加载历史详情失败");
    }
  }

  return (
    <section className="history-layout">
      <div className="tool-row">
        <button onClick={() => load()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} />刷新</button>
      </div>
      <div className="history-grid">
        <div className="history-list">
          {items.map((item) => (
            <button key={item.id} className={detail?.id === item.id ? "selected" : ""} onClick={() => openDetail(item.id)}>
              <strong>{item.title}</strong>
              <span>{new Date(item.updated_at).toLocaleString()}</span>
            </button>
          ))}
          {hasMore && <button onClick={() => load(offset, true)} disabled={loading}>加载更多</button>}
        </div>
        <div className="history-detail">
          {detail ? detail.messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={{ id: message.id, role: message.role, content: message.content, artifacts: message.artifacts || [] }}
            />
          )) : <div className="empty-state">选择一条历史记录</div>}
        </div>
      </div>
    </section>
  );
}

function SettingsView({ setError }: { setError: (value: string | null) => void }) {
  const [apiBaseValue, setApiBaseValue] = useState("");
  const [models, setModels] = useState<ModelSettings | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([getApiBase(), getModelSettings()])
      .then(([base, modelSettings]) => {
        setApiBaseValue(base);
        setModels(modelSettings);
      })
      .catch((error) => setError(error instanceof Error ? error.message : "加载设置失败"));
  }, []);

  async function saveSettings() {
    if (!models) return;
    setLoading(true);
    setError(null);
    try {
      await setApiBase(apiBaseValue);
      setModels(await updateModelSettings(models));
    } catch (error) {
      setError(error instanceof Error ? error.message : "保存设置失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="settings-layout">
      <label>
        后端地址
        <input value={apiBaseValue} onChange={(event) => setApiBaseValue(event.target.value)} />
      </label>
      <label>
        文本总结模型
        <input value={models?.text_summary_model || ""} placeholder={models?.defaults.text_summary_model} onChange={(event) => setModels((value) => value && { ...value, text_summary_model: event.target.value })} />
      </label>
      <label>
        视觉分析模型
        <input value={models?.vision_analysis_model || ""} placeholder={models?.defaults.vision_analysis_model} onChange={(event) => setModels((value) => value && { ...value, vision_analysis_model: event.target.value })} />
      </label>
      <label>
        对话模型
        <input value={models?.conversation_model || ""} placeholder={models?.defaults.conversation_model} onChange={(event) => setModels((value) => value && { ...value, conversation_model: event.target.value })} />
      </label>
      <button className="primary-button" onClick={saveSettings} disabled={loading || !models}>
        {loading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
        保存
      </button>
    </section>
  );
}

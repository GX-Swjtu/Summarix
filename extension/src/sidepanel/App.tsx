import {
  AlertTriangle,
  Camera,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  FileText,
  History,
  ImagePlus,
  Link,
  ListChecks,
  Loader2,
  LogIn,
  LogOut,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  Sparkles,
  Square,
  Wand2,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

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
import type {
  ActiveTabInfo,
  AdkEvent,
  Artifact,
  ConversationDetail,
  ConversationSummary,
  ExtractedPage,
  MessageAttachment,
  ModelSettings,
  User
} from "../shared/types";
import { captureVisibleTab, extractCurrentPage, getActiveTabInfo } from "./chrome";

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

type QuickAction = {
  label: string;
  prompt: string;
  icon: LucideIcon;
  needsPage?: boolean;
  needsScreenshot?: boolean;
};

const HISTORY_PAGE_SIZE = 20;
const QUICK_ACTIONS: QuickAction[] = [
  {
    label: "总结页面",
    prompt: "请用 Markdown 总结当前网页：先给一句话结论，再列出关键要点、事实依据和可行动建议。",
    icon: Sparkles,
    needsPage: true
  },
  {
    label: "提炼要点",
    prompt: "请提炼当前网页最重要的 5 个要点，并说明每个要点为什么重要。",
    icon: ListChecks,
    needsPage: true
  },
  {
    label: "解释截图",
    prompt: "请结合当前页面截图，说明画面中最值得关注的信息、可能的含义和下一步建议。",
    icon: Camera,
    needsScreenshot: true
  },
  {
    label: "风险/待办",
    prompt: "请从当前网页中找出潜在风险、限制条件、待办事项和我应该继续追问的问题。",
    icon: AlertTriangle,
    needsPage: true
  },
  {
    label: "小红书文案",
    prompt: "请将当前网页主体文章转换为小红书文案，严格使用：爆点标题、开场引子、正文、标签、互动引导。",
    icon: MessageSquare,
    needsPage: true
  },
  {
    label: "短视频脚本",
    prompt: "请将当前网页主体文章转换为短视频脚本，严格使用：选题标题、3 秒钩子、分镜表、结尾行动引导。",
    icon: FileText,
    needsPage: true
  },
  {
    label: "继续追问",
    prompt: "请基于我们已有上下文，给我 3 个最值得继续追问的问题，并说明它们能帮助我澄清什么。",
    icon: Wand2
  }
];

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

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function pageLengthText(page: ExtractedPage): string {
  if (!page.text) return "已记录页面信息";
  return `${Math.max(1, Math.round(page.text.length / 100) / 10)}k 字`;
}

function getNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(getNodeText).join("");
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { children?: ReactNode } }).props;
    return getNodeText(props?.children);
  }
  return "";
}

async function copyText(text: string): Promise<void> {
  if (!text) return;
  await navigator.clipboard.writeText(text);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [view, setView] = useState<View>("chat");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resumeDetail, setResumeDetail] = useState<ConversationDetail | null>(null);

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
        <div className="brand-lockup">
          <div className="brand-mark"><Sparkles size={18} /></div>
          <div>
            <strong>Summarix</strong>
            <span>{user.email}</span>
          </div>
        </div>
        <button
          className="icon-button subtle"
          title="退出登录"
          onClick={async () => {
            setBusy(true);
            await logout().finally(() => setBusy(false));
            setUser(null);
          }}
          disabled={busy}
        >
          {busy ? <Loader2 className="spin" size={18} /> : <LogOut size={18} />}
        </button>
      </header>

      <nav className="tabs" aria-label="主导航">
        <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}><MessageSquare size={16} />聊天</button>
        <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}><History size={16} />历史</button>
        <button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}><Settings size={16} />设置</button>
      </nav>

      {error && (
        <div className="notice" role="alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button title="关闭提示" onClick={() => setError(null)}><X size={14} /></button>
        </div>
      )}

      <main className="main-panel">
        {view === "chat" && (
          <ChatView
            resumeConversation={resumeDetail}
            onResumed={() => setResumeDetail(null)}
            setError={setError}
          />
        )}
        {view === "history" && (
          <HistoryView
            setError={setError}
            onContinue={(detail) => {
              setResumeDetail(detail);
              setView("chat");
            }}
          />
        )}
        {view === "settings" && <SettingsView setError={setError} />}
      </main>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="auth-shell loading-shell">
      <div className="brand-row"><Sparkles size={24} /><strong>Summarix</strong></div>
      <div className="loading-pill"><Loader2 className="spin" size={18} />正在唤醒助手</div>
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
        <Sparkles size={24} />
        <strong>Summarix</strong>
      </div>
      <form className="auth-form" onSubmit={submit}>
        <div className="auth-heading">
          <h1>{mode === "login" ? "欢迎回来" : "创建账号"}</h1>
          <p>登录后即可同步网页分析、截图问答和历史记录。</p>
        </div>
        <label>
          邮箱
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
        </label>
        {props.error && <div className="notice inline"><AlertTriangle size={16} />{props.error}</div>}
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

function ChatView({
  resumeConversation,
  onResumed,
  setError
}: {
  resumeConversation: ConversationDetail | null;
  onResumed: () => void;
  setError: (value: string | null) => void;
}) {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [page, setPage] = useState<ExtractedPage | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTabInfo | null>(null);
  const [contextDirty, setContextDirty] = useState(false);
  const [contextNote, setContextNote] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftAttachment[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const pageRef = useRef<ExtractedPage | null>(null);
  const activeTabRef = useRef<ActiveTabInfo | null>(null);
  const draftsRef = useRef<DraftAttachment[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const pageStatus = useMemo(() => {
    if (extracting) return "正在读取当前网页";
    if (!page) return contextNote || "尚未读取网页正文";
    const title = page.title || activeTab?.title || "当前网页";
    return `${title} · ${pageLengthText(page)}`;
  }, [activeTab?.title, contextNote, extracting, page]);

  const hasContext = Boolean(page?.text || drafts.length > 0 || conversationId);
  const busy = sending || extracting || capturing;

  useEffect(() => {
    pageRef.current = page;
  }, [page]);

  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  useEffect(() => {
    draftsRef.current = drafts;
  }, [drafts]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      messageEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    }, 20);
    return () => window.clearTimeout(timer);
  }, [messages, sending]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [input]);

  useEffect(() => {
    let active = true;
    async function syncActiveTab(initial = false) {
      try {
        const tab = await getActiveTabInfo();
        if (!active) return;
        setActiveTab(tab);
        activeTabRef.current = tab;
        if (initial && !pageRef.current) {
          await extractPage({ silent: true });
          return;
        }
        if (!initial && pageRef.current && tab.url && tab.url !== pageRef.current.url) {
          setContextDirty(true);
          setContextNote("检测到标签页已变化，可刷新网页上下文");
        }
      } catch {
        if (active && initial) setContextNote("当前页面暂时无法自动读取");
      }
    }
    syncActiveTab(true);
    const interval = window.setInterval(() => syncActiveTab(false), 3000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      for (const draft of draftsRef.current) URL.revokeObjectURL(draft.previewUrl);
    };
  }, []);

  useEffect(() => {
    if (!resumeConversation) return;
    setConversationId(resumeConversation.id);
    setMessages(
      resumeConversation.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        artifacts: message.artifacts || []
      }))
    );
    if (resumeConversation.page_url || resumeConversation.page_title) {
      setPage({
        url: resumeConversation.page_url || "",
        title: resumeConversation.page_title || resumeConversation.title,
        text: ""
      });
      setContextDirty(true);
      setContextNote("已载入历史会话，可刷新当前网页正文后继续追问");
    }
    onResumed();
  }, [onResumed, resumeConversation]);

  function addAttachmentDrafts(nextDrafts: DraftAttachment[]) {
    setError(null);
    setDrafts((items) => [...items, ...nextDrafts]);
  }

  function addAttachmentFiles(files: Iterable<File>, source: "screenshot" | "upload"): DraftAttachment[] {
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length === 0) {
      setError("请选择图片文件");
      return [];
    }
    const nextDrafts = imageFiles.map((file) => ({
      id: makeLocalId(),
      file,
      filename: file.name || "image.png",
      source,
      previewUrl: URL.createObjectURL(file),
      uploading: false,
      error: null
    }));
    addAttachmentDrafts(nextDrafts);
    return nextDrafts;
  }

  function removeDraft(id: string) {
    setDrafts((items) => {
      const target = items.find((item) => item.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return items.filter((item) => item.id !== id);
    });
  }

  async function extractPage(options: { silent?: boolean } = {}): Promise<ExtractedPage | null> {
    if (extracting) return pageRef.current;
    if (!options.silent) setError(null);
    setExtracting(true);
    try {
      const nextPage = await extractCurrentPage();
      const tab = await getActiveTabInfo().catch(() => null);
      setPage(nextPage);
      pageRef.current = nextPage;
      if (tab) {
        setActiveTab(tab);
        activeTabRef.current = tab;
      }
      setContextDirty(false);
      setContextNote(null);
      return nextPage;
    } catch (error) {
      const message = error instanceof Error ? error.message : "提取网页失败";
      if (options.silent) {
        setContextNote("当前页面无法自动读取，可尝试截图或上传图片");
      } else {
        setError(message);
      }
      return null;
    } finally {
      setExtracting(false);
    }
  }

  async function createScreenshotDraft(): Promise<DraftAttachment | null> {
    setCapturing(true);
    try {
      const dataUrl = await captureVisibleTab();
      const blob = await (await fetch(dataUrl)).blob();
      const file = new File([blob], `screenshot-${Date.now()}.png`, { type: blob.type || "image/png" });
      return {
        id: makeLocalId(),
        file,
        filename: file.name,
        source: "screenshot",
        previewUrl: URL.createObjectURL(file),
        uploading: false,
        error: null
      };
    } catch (error) {
      setError(error instanceof Error ? error.message : "截图失败");
      return null;
    } finally {
      setCapturing(false);
    }
  }

  async function captureAndInsert() {
    setError(null);
    const draft = await createScreenshotDraft();
    if (draft) addAttachmentDrafts([draft]);
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

  async function uploadDrafts(items: DraftAttachment[]): Promise<MessageAttachment[]> {
    if (items.length === 0) return [];
    const ids = new Set(items.map((item) => item.id));
    setDrafts((current) => current.map((item) => (ids.has(item.id) ? { ...item, uploading: true, error: null } : item)));
    const uploaded: MessageAttachment[] = [];
    for (const draft of items) {
      try {
        const artifact = await uploadArtifact(draft.file, draft.filename, draft.source);
        uploaded.push({ ...artifact, previewUrl: draft.previewUrl });
      } catch (error) {
        setDrafts((current) => current.map((item) => (item.id === draft.id ? { ...item, uploading: false, error: error instanceof Error ? error.message : "上传失败" } : item)));
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

  async function sendPrompt(messageText = input.trim(), extraDrafts: DraftAttachment[] = [], contextOverride?: ExtractedPage | null) {
    const text = messageText.trim();
    if (!text || sending) return;
    setError(null);
    setSending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const assistantId = makeLocalId();
    try {
      const draftSnapshot = [...drafts, ...extraDrafts];
      const uploadedArtifacts = await uploadDrafts(draftSnapshot);
      const userMessage: LocalMessage = { id: makeLocalId(), role: "user", content: text, artifacts: uploadedArtifacts };
      setMessages((items) => [...items, userMessage, { id: assistantId, role: "assistant", content: "" }]);
      setInput("");
      setDrafts([]);
      const requestPage = contextOverride === undefined ? page : contextOverride;
      await streamChat({
        conversationId,
        message: text,
        context: requestPage ? { page_url: requestPage.url, page_title: requestPage.title, page_text: requestPage.text } : null,
        artifactIds: uploadedArtifacts.map((artifact) => artifact.id),
        signal: controller.signal,
        onConversation: (payload) => setConversationId(payload.id),
        onAdkEvent: (event) => applyAdkEvent(assistantId, event)
      });
    } catch (error) {
      if (isAbortError(error)) {
        setMessages((items) => items.map((item) => (item.id === assistantId && !item.content.trim() ? { ...item, content: "已停止生成。" } : item)));
      } else {
        setError(error instanceof Error ? error.message : "发送失败");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setSending(false);
    }
  }

  async function runQuickAction(action: QuickAction) {
    let requestPage = page;
    const extraDrafts: DraftAttachment[] = [];
    if (action.needsPage && (!requestPage || contextDirty)) {
      requestPage = await extractPage();
      if (!requestPage) return;
    }
    if (action.needsScreenshot && drafts.length === 0) {
      const screenshot = await createScreenshotDraft();
      if (!screenshot) return;
      extraDrafts.push(screenshot);
    }
    await sendPrompt(action.prompt, extraDrafts, requestPage);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void sendPrompt();
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
      <div className="context-bar">
        <button title="提取正文" onClick={() => void extractPage()} disabled={extracting || sending}>
          {extracting ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
          正文
        </button>
        <button title="截图插入" onClick={() => void captureAndInsert()} disabled={capturing || sending}>
          {capturing ? <Loader2 className="spin" size={16} /> : <Camera size={16} />}
          截图
        </button>
        <div className={`context-status${contextDirty ? " dirty" : ""}`}>
          <Link size={14} />
          <span title={page?.url || activeTab?.url || pageStatus}>{pageStatus}</span>
          {contextDirty && (
            <button className="text-button" onClick={() => void extractPage()} disabled={extracting || sending}>刷新</button>
          )}
        </div>
      </div>

      <div className="message-list">
        {messages.length === 0 && (
          <div className="empty-state">
            <Sparkles size={22} />
            <h2>我可以帮你读懂当前页面</h2>
            <p>{hasContext ? "选择一个快捷动作，或直接输入你的问题。" : "正在尝试读取网页，也可以先截图或上传图片。"}</p>
            <QuickActionGrid actions={QUICK_ACTIONS} disabled={busy} onAction={runQuickAction} />
          </div>
        )}
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            streaming={sending && message.role === "assistant" && !message.content}
            onToggleThought={toggleThought}
          />
        ))}
        <div ref={messageEndRef} />
      </div>

      {messages.length > 0 && <QuickActionGrid actions={QUICK_ACTIONS} compact disabled={busy} onAction={runQuickAction} />}
      {dragActive && <div className="drop-hint"><ImagePlus size={20} />松开即可添加图片</div>}
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
        <button className="icon-button attach" title="插入图片" onClick={() => fileInputRef.current?.click()} disabled={sending}>
          <ImagePlus size={18} />
        </button>
        <textarea
          ref={textareaRef}
          value={input}
          onPaste={handlePaste}
          onKeyDown={handleComposerKeyDown}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入问题，Shift + Enter 换行"
          rows={1}
        />
        {sending ? (
          <button className="icon-button send stop" title="停止生成" onClick={() => abortRef.current?.abort()}>
            <Square size={16} />
          </button>
        ) : (
          <button className="icon-button send" title="发送" onClick={() => void sendPrompt()} disabled={!input.trim()}>
            <Send size={18} />
          </button>
        )}
      </div>
    </section>
  );
}

function QuickActionGrid({
  actions,
  compact = false,
  disabled,
  onAction
}: {
  actions: QuickAction[];
  compact?: boolean;
  disabled: boolean;
  onAction: (action: QuickAction) => void | Promise<void>;
}) {
  return (
    <div className={`quick-actions${compact ? " compact" : ""}`}>
      {actions.map((action) => {
        const Icon = action.icon;
        return (
          <button key={action.label} type="button" disabled={disabled} onClick={() => void onAction(action)}>
            <Icon size={15} />
            {action.label}
          </button>
        );
      })}
    </div>
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

function MessageBubble({
  message,
  streaming = false,
  onToggleThought
}: {
  message: LocalMessage;
  streaming?: boolean;
  onToggleThought?: (id: string) => void;
}) {
  const hasThought = Boolean(message.thought?.trim());
  const [copied, setCopied] = useState(false);
  const roleClass = message.role === "user" ? "user" : "assistant";

  async function copyMessage() {
    await copyText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <article className={`message ${roleClass}`}>
      {message.artifacts && message.artifacts.length > 0 && (
        <div className="message-attachments">
          {message.artifacts.map((artifact) => <AttachmentPreview artifact={artifact} key={artifact.id} />)}
        </div>
      )}
      <div className="message-text">
        {streaming ? <TypingIndicator /> : <MarkdownMessage content={message.content || (roleClass === "assistant" ? "..." : "")} />}
      </div>
      <div className="message-footer">
        {message.content.trim() && (
          <button type="button" className="ghost-action" title="复制消息" onClick={() => void copyMessage()}>
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? "已复制" : "复制"}
          </button>
        )}
        {hasThought && roleClass === "assistant" && (
          <button type="button" className="ghost-action" onClick={() => onToggleThought?.(message.id)}>
            {message.thoughtOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            思考
          </button>
        )}
      </div>
      {hasThought && roleClass === "assistant" && message.thoughtOpen && (
        <div className="thought-content">
          <MarkdownMessage content={message.thought || ""} />
        </div>
      )}
    </article>
  );
}

function TypingIndicator() {
  return (
    <div className="typing-indicator" aria-label="AI 正在生成">
      <span />
      <span />
      <span />
    </div>
  );
}

const markdownComponents: Components = {
  a({ children, href }) {
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
  },
  pre({ children }) {
    return <CodePanel>{children}</CodePanel>;
  }
};

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function CodePanel({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = getNodeText(children);

  async function copyCode() {
    await copyText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="code-panel">
      <button type="button" title="复制代码" onClick={() => void copyCode()}>
        {copied ? <Check size={13} /> : <Copy size={13} />}
        {copied ? "已复制" : "复制代码"}
      </button>
      <pre>{children}</pre>
    </div>
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
      <figcaption title={artifact.filename}>{artifact.filename}</figcaption>
    </figure>
  );
}

function HistoryView({
  setError,
  onContinue
}: {
  setError: (value: string | null) => void;
  onContinue: (detail: ConversationDetail) => void;
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return items;
    return items.filter((item) => [item.title, item.page_title, item.page_url].filter(Boolean).some((value) => value!.toLowerCase().includes(keyword)));
  }, [items, query]);

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
    void load();
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
      <div className="history-toolbar">
        <div className="search-box">
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索已加载历史" />
        </div>
        <button onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "spin" : ""} size={16} />
          刷新
        </button>
      </div>
      <div className="history-grid">
        <div className="history-list">
          {filteredItems.map((item) => (
            <button key={item.id} className={detail?.id === item.id ? "selected" : ""} onClick={() => void openDetail(item.id)}>
              <strong>{item.title}</strong>
              <span>{item.page_title || item.page_url || "普通对话"}</span>
              <small>{formatDate(item.updated_at)}</small>
            </button>
          ))}
          {filteredItems.length === 0 && <div className="empty-mini">没有匹配的历史</div>}
          {hasMore && <button className="load-more" onClick={() => void load(offset, true)} disabled={loading}>加载更多</button>}
        </div>
        <div className="history-detail">
          {detail ? (
            <>
              <div className="detail-header">
                <div>
                  <strong>{detail.title}</strong>
                  <span>{detail.page_title || detail.page_url || "历史会话"}</span>
                </div>
                <button onClick={() => onContinue(detail)}><MessageSquare size={15} />继续</button>
              </div>
              <div className="history-messages">
                {detail.messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    message={{ id: message.id, role: message.role, content: message.content, artifacts: message.artifacts || [] }}
                  />
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state small">
              <History size={20} />
              <h2>选择一条历史记录</h2>
              <p>可查看完整 Markdown 回复、附件和继续对话。</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function SettingsView({ setError }: { setError: (value: string | null) => void }) {
  const [apiBaseValue, setApiBaseValue] = useState("");
  const [models, setModels] = useState<ModelSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getApiBase(), getModelSettings()])
      .then(([base, modelSettings]) => {
        setApiBaseValue(base);
        setModels(modelSettings);
      })
      .catch((error) => setError(error instanceof Error ? error.message : "加载设置失败"));
  }, [setError]);

  function resetModels() {
    setModels((value) => value && {
      ...value,
      text_summary_model: null,
      vision_analysis_model: null,
      conversation_model: null,
      xiaohongshu_model: null,
      short_video_script_model: null
    });
  }

  async function saveSettings() {
    if (!models) return;
    try {
      new URL(apiBaseValue);
    } catch {
      setError("后端地址需要是完整 URL，例如 http://127.0.0.1:8000");
      return;
    }
    setLoading(true);
    setError(null);
    setSavedAt(null);
    try {
      await setApiBase(apiBaseValue);
      setModels(await updateModelSettings(models));
      setSavedAt(new Date().toLocaleTimeString());
    } catch (error) {
      setError(error instanceof Error ? error.message : "保存设置失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="settings-layout">
      <div className="settings-section">
        <div className="section-heading">
          <div>
            <strong>连接</strong>
            <span>侧边栏会通过这个地址访问 FastAPI 后端。</span>
          </div>
        </div>
        <label>
          后端地址
          <input value={apiBaseValue} onChange={(event) => setApiBaseValue(event.target.value)} placeholder="http://127.0.0.1:8000" />
        </label>
      </div>

      <div className="settings-section">
        <div className="section-heading">
          <div>
            <strong>模型</strong>
            <span>留空时使用后端默认值；快捷文案和脚本任务会优先走对应模型，若会结合截图改写，请确保对应模型支持 vision 输入。</span>
          </div>
          <button type="button" onClick={resetModels} disabled={!models}><RotateCcw size={15} />默认</button>
        </div>
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
        <label>
          小红书文案模型
          <input value={models?.xiaohongshu_model || ""} placeholder={models?.defaults.xiaohongshu_model} onChange={(event) => setModels((value) => value && { ...value, xiaohongshu_model: event.target.value })} />
        </label>
        <label>
          短视频脚本模型
          <input value={models?.short_video_script_model || ""} placeholder={models?.defaults.short_video_script_model} onChange={(event) => setModels((value) => value && { ...value, short_video_script_model: event.target.value })} />
        </label>
      </div>

      <button className="primary-button" onClick={() => void saveSettings()} disabled={loading || !models}>
        {loading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
        保存设置
      </button>
      {savedAt && <div className="save-state"><Check size={15} />已在 {savedAt} 保存</div>}
    </section>
  );
}

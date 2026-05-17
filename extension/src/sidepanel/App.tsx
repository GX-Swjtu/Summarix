import {
  AlertTriangle,
  Camera,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
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
  Monitor,
  Moon,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  Sparkles,
  Square,
  Sun,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Wand2,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import {
  clearCachedUser,
  clearRememberedAuth,
  deleteHistory,
  getApiBase,
  getArtifactObjectUrl,
  getDefaultApiBase,
  getHistoryDetail,
  getMe,
  getModelSettings,
  isAuthRequiredError,
  listHistory,
  login,
  logout,
  cacheModelSelection,
  persistApiBasePreference,
  persistRememberedAuth,
  readCachedModelSelection,
  readCachedUser,
  readRememberedAuth,
  register,
  resetApiBase,
  streamChat,
  streamSuggestedQuestions,
  submitFeedback,
  updateModelSettings,
  uploadArtifact
} from "../shared/api";
import type {
  ActiveTabInfo,
  AdkEvent,
  Artifact,
  AvailableModelOption,
  ConversationDetail,
  ConversationSummary,
  ExtractedPage,
  FeedbackRating,
  MessageAttachment,
  ModelSettings,
  ResolvedTheme,
  ThemePreference,
  ThinkingMode,
  User
} from "../shared/types";
import { applyThemePreference, cacheThemePreference, getSystemTheme, normalizeThemePreference, resolveThemePreference } from "../shared/theme";
import { captureVisibleTab, extractCurrentPage, getActiveTabInfo } from "./chrome";

type View = "chat" | "history" | "settings";

type LocalMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  persisted?: boolean;
  traceId?: string | null;
  adkInvocationId?: string | null;
  thought?: string;
  thoughtOpen?: boolean;
  artifacts?: MessageAttachment[];
  suggestedQuestions?: string[];
  suggestionsVisible?: boolean;
  suggestionsLoading?: boolean;
  feedback?: {
    id?: string;
    rating: FeedbackRating | null;
    pending?: boolean;
    error?: string | null;
    langwatchSyncStatus?: string;
  };
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

type ContextSendMode = "followup" | "attachPage";

type SendPromptOptions = {
  extraDrafts?: DraftAttachment[];
  contextMode?: ContextSendMode;
};

type MessageScrollBehavior = "instant" | "smooth";

const HISTORY_PAGE_SIZE = 20;
const SUGGESTED_QUESTION_COUNT = 3;
const AUTO_SCROLL_BOTTOM_THRESHOLD = 64;
const PROGRAMMATIC_SCROLL_LOCK_MS = 400;
const USER_SCROLL_INTENT_MS = 250;
const REPOSITORY_URL = "https://github.com/GX-Swjtu/Summarix";
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

const THINKING_MODE_OPTIONS: { value: ThinkingMode; label: string; title: string }[] = [
  { value: "default", label: "默认", title: "跟随模型默认行为，不强制启用或关闭深度思考" },
  { value: "enabled", label: "开启", title: "强制启用深度思考（逐步推理），适合复杂任务，响应较慢" },
  { value: "disabled", label: "关闭", title: "强制关闭深度思考，响应更快、成本更低" }
];

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: LucideIcon }[] = [
  { value: "default", label: "默认", icon: Monitor },
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon }
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

function normalizeApiBaseInput(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function pageLengthText(page: ExtractedPage): string {
  if (!page.text) return "已记录页面信息";
  return `${Math.max(1, Math.round(page.text.length / 100) / 10)}k 字`;
}

function formatReferenceLength(length?: number | null): string {
  if (!length) return "已记录页面信息";
  if (length >= 1000) return `${Math.max(1, Math.round(length / 100) / 10)}k 字`;
  return `${length} 字`;
}

function getReferenceSource(url?: string | null): string {
  if (!url) return "网页参考";
  try {
    return new URL(url).hostname || url;
  } catch {
    return url;
  }
}

function getReferenceTitle(artifact: MessageAttachment | Artifact): string {
  return artifact.page_title || artifact.filename.replace(/\.txt$/i, "") || getReferenceSource(artifact.page_url) || "当前网页";
}

function makePageTextExcerpt(text: string, limit = 120): string | null {
  const excerpt = text.replace(/\s+/g, " ").trim();
  if (!excerpt) return null;
  return excerpt.length > limit ? `${excerpt.slice(0, limit).trim()}...` : excerpt;
}

function makePageReferenceAttachment(page: ExtractedPage): MessageAttachment {
  const title = page.title || getReferenceSource(page.url) || "当前网页";
  return {
    id: `page-${makeLocalId()}`,
    filename: `${title}.txt`,
    mime_type: "text/plain; charset=utf-8",
    size_bytes: new TextEncoder().encode(page.text || title).length,
    version: 0,
    source: "page_text",
    page_url: page.url,
    page_title: title,
    text_excerpt: makePageTextExcerpt(page.text),
    text_length: page.text.length
  };
}

function mergeReferenceArtifacts(current: MessageAttachment[] = [], references: Artifact[] = []): MessageAttachment[] {
  if (references.length === 0) return current;
  return [...references, ...current.filter((artifact) => artifact.source !== "page_text")];
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

export function App({ initialThemePreference = "default" }: { initialThemePreference?: ThemePreference }) {
  const [user, setUser] = useState<User | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [view, setView] = useState<View>("chat");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resumeDetail, setResumeDetail] = useState<ConversationDetail | null>(null);
  const [themePreference, setThemePreference] = useState<ThemePreference>(initialThemePreference);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(() => getSystemTheme());
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const [modelSettingsLoading, setModelSettingsLoading] = useState(false);
  const [modelSettingsSaving, setModelSettingsSaving] = useState(false);
  const resolvedTheme = useMemo(() => resolveThemePreference(themePreference, systemTheme), [systemTheme, themePreference]);

  const handleAuthRequired = useCallback(async () => {
    await clearCachedUser();
    setUser(null);
    setError("登录状态已失效，请重新登录。");
  }, []);

  const triggerAuthRequired = useCallback(() => {
    void handleAuthRequired();
  }, [handleAuthRequired]);

  const persistThemePreference = useCallback((nextThemePreference: ThemePreference) => {
    setThemePreference(nextThemePreference);
    void cacheThemePreference(nextThemePreference);
  }, []);

  useEffect(() => {
    applyThemePreference(themePreference, systemTheme);
  }, [systemTheme, themePreference]);

  useEffect(() => {
    if (themePreference !== "default" || typeof window === "undefined" || !window.matchMedia) return;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const updateSystemTheme = () => setSystemTheme(mediaQuery.matches ? "dark" : "light");
    updateSystemTheme();
    mediaQuery.addEventListener("change", updateSystemTheme);
    return () => mediaQuery.removeEventListener("change", updateSystemTheme);
  }, [themePreference]);

  useEffect(() => {
    if (!user) {
      setModelSettings(null);
      return;
    }
    let active = true;
    setModelSettingsLoading(true);
    readCachedModelSelection()
      .then((cachedSelection) => {
        if (!active || !cachedSelection) return;
        setModelSettings((value) => value ?? {
          theme: themePreference,
          primary_model_id: cachedSelection.primary_model_id,
          primary_thinking_mode: cachedSelection.primary_thinking_mode,
          available_models: [],
          defaults: {}
        });
      })
      .catch(() => undefined);
    getModelSettings()
      .then((settings) => {
        if (!active) return;
        const nextThemePreference = normalizeThemePreference(settings.theme);
        setThemePreference(nextThemePreference);
        setModelSettings({ ...settings, theme: nextThemePreference });
        void cacheThemePreference(nextThemePreference);
        void cacheModelSelection({
          primary_model_id: settings.primary_model_id || null,
          primary_thinking_mode: settings.primary_thinking_mode
        });
      })
      .catch((error) => {
        if (!active) return;
        if (isAuthRequiredError(error)) void handleAuthRequired();
        else setError(error instanceof Error ? error.message : "加载主题设置失败");
      })
      .finally(() => {
        if (active) setModelSettingsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [handleAuthRequired, user]);

  const updatePrimaryModelSelection = useCallback(async (selection: { primary_model_id: string | null; primary_thinking_mode: ThinkingMode }) => {
    if (!modelSettings || modelSettingsSaving) return false;
    const previousSettings = modelSettings;
    const optimisticSettings = {
      ...modelSettings,
      primary_model_id: selection.primary_model_id,
      primary_thinking_mode: selection.primary_thinking_mode
    };
    setModelSettings(optimisticSettings);
    setModelSettingsSaving(true);
    setError(null);
    try {
      const nextSettings = await updateModelSettings(optimisticSettings);
      setModelSettings(nextSettings);
      void cacheModelSelection({
        primary_model_id: nextSettings.primary_model_id || null,
        primary_thinking_mode: nextSettings.primary_thinking_mode
      });
      return true;
    } catch (error) {
      setModelSettings(previousSettings);
      if (isAuthRequiredError(error)) void handleAuthRequired();
      else setError(error instanceof Error ? error.message : "模型设置保存失败");
      return false;
    } finally {
      setModelSettingsSaving(false);
    }
  }, [handleAuthRequired, modelSettings, modelSettingsSaving]);

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      const cachedUser = await readCachedUser();
      if (active && cachedUser) setUser(cachedUser);
      if (!active) return;
      setBootstrapping(false);
    }
    restoreSession().catch(() => {
      if (active) setBootstrapping(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const handleLogout = useCallback(async () => {
    setBusy(true);
    try {
      await logout();
    } catch (error) {
      setError(error instanceof Error ? error.message : "退出登录失败");
    } finally {
      setBusy(false);
      setUser(null);
    }
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
            onAuthRequired={triggerAuthRequired}
            modelSettings={modelSettings}
            modelSettingsLoading={modelSettingsLoading}
            modelSettingsSaving={modelSettingsSaving}
            onModelSelectionChange={updatePrimaryModelSelection}
          />
        )}
        {view === "history" && (
          <HistoryView
            setError={setError}
            onAuthRequired={handleAuthRequired}
            onContinue={(detail) => {
              setResumeDetail(detail);
              setView("chat");
            }}
          />
        )}
        {view === "settings" && (
          <SettingsView
            setError={setError}
            onAuthRequired={triggerAuthRequired}
            themePreference={themePreference}
            resolvedTheme={resolvedTheme}
            onThemePreferenceChange={setThemePreference}
            onThemePreferencePersisted={persistThemePreference}
            onLogout={() => void handleLogout()}
            logoutPending={busy}
          />
        )}
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
  const defaultApiBase = getDefaultApiBase();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiBaseValue, setApiBaseValue] = useState(defaultApiBase);
  const [rememberEmail, setRememberEmail] = useState(true);
  const [rememberPassword, setRememberPassword] = useState(false);
  const [connectionSettingsOpen, setConnectionSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getApiBase(), readRememberedAuth()])
      .then(([apiBase, remembered]) => {
        if (!active) return;
        setApiBaseValue(apiBase);
        setEmail(remembered.email);
        setPassword(remembered.password);
        setRememberEmail(remembered.rememberEmail);
        setRememberPassword(remembered.rememberPassword);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  async function applyApiBaseSelection(): Promise<boolean> {
    const normalizedApiBase = normalizeApiBaseInput(apiBaseValue);
    try {
      new URL(normalizedApiBase);
    } catch {
      props.setError("后端地址需要是完整 URL，例如 http://127.0.0.1:8000");
      return false;
    }
    await persistApiBasePreference(normalizedApiBase);
    setApiBaseValue(normalizedApiBase || defaultApiBase);
    return true;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    props.setError(null);
    if (!(await applyApiBaseSelection())) return;
    const normalizedEmail = email.trim();
    setLoading(true);
    try {
      const nextUser = mode === "login" ? await login(normalizedEmail, password) : await register(normalizedEmail, password);
      await persistRememberedAuth({
        email: normalizedEmail,
        password,
        rememberEmail,
        rememberPassword
      });
      props.onAuthed(nextUser);
    } catch (error) {
      props.setError(error instanceof Error ? error.message : "认证失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <section className="auth-hero auth-hero-compact">
        <div className="brand-row">
          <Sparkles size={24} />
          <strong>Summarix</strong>
        </div>
        <div className="auth-heading">
          <h1>{mode === "login" ? "欢迎回来" : "创建账号"}</h1>
          <p>{mode === "login" ? "登录后即可同步网页分析、截图问答和历史记录。" : "创建账号后即可开始同步网页分析、截图问答和历史记录。"}</p>
        </div>
      </section>
      <form className="auth-form auth-card auth-form-card" onSubmit={submit}>
        <div className="auth-heading">
          <h2>{mode === "login" ? "登录到你的工作台" : "创建新的工作台账号"}</h2>
          <p>{mode === "login" ? "默认连接本地后端，只有连接异常时才需要调整设置。" : "先创建账号；如果默认连接不可用，再展开设置修改后端地址。"}</p>
        </div>
        <button
          type="button"
          className={`auth-settings-toggle${connectionSettingsOpen ? " open" : ""}`}
          onClick={() => setConnectionSettingsOpen((value) => !value)}
          aria-expanded={connectionSettingsOpen ? "true" : "false"}
          aria-controls="auth-connection-settings"
        >
          <span className="auth-settings-toggle-copy">
            <span className="auth-settings-toggle-title"><Settings size={15} />设置</span>
          </span>
          {connectionSettingsOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {connectionSettingsOpen && (
          <div className="auth-section" id="auth-connection-settings">
            <div className="auth-section-heading">
              <strong>连接设置</strong>
              <button
                type="button"
                onClick={async () => {
                  props.setError(null);
                  await resetApiBase();
                  setApiBaseValue(defaultApiBase);
                }}
              >
                <RotateCcw size={15} />恢复默认
              </button>
            </div>
            <label>
              后端地址
              <input value={apiBaseValue} onChange={(event) => setApiBaseValue(event.target.value)} placeholder={defaultApiBase} />
            </label>
            <p className="field-hint">编译默认值：{defaultApiBase}</p>
          </div>
        )}
        <label>
          邮箱
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
        </label>
        <div className="auth-options">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={rememberEmail}
              onChange={(event) => {
                const checked = event.target.checked;
                setRememberEmail(checked);
                if (!checked) {
                  setRememberPassword(false);
                  void clearRememberedAuth();
                }
              }}
            />
            记住账号
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={rememberPassword}
              onChange={(event) => {
                const checked = event.target.checked;
                setRememberPassword(checked);
                if (checked) {
                  setRememberEmail(true);
                  return;
                }
                void persistRememberedAuth({
                  email: email.trim(),
                  password: "",
                  rememberEmail,
                  rememberPassword: false
                });
              }}
            />
            记住密码
          </label>
        </div>
        <p className="field-hint">记住密码后，仅会保存在当前浏览器本地扩展存储中。</p>
        {props.error && <div className="notice inline"><AlertTriangle size={16} />{props.error}</div>}
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <LogIn size={16} />}
          {mode === "login" ? "登录" : "注册"}
        </button>
        <div className="auth-actions">
          <button type="button" className="auth-mode-button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "没有账号？创建账号" : "已有账号？返回登录"}
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!(await applyApiBaseSelection())) return;
              setLoading(true);
              props.setError(null);
              try {
                const restored = await getMe();
                if (restored) {
                  props.onAuthed(restored);
                  return;
                }
                props.setError("当前没有可继续的登录状态，请直接登录。");
              } catch (error) {
                props.setError(error instanceof Error ? error.message : "继续上次登录失败");
              } finally {
                setLoading(false);
              }
            }}
          >
            继续上次登录
          </button>
        </div>
      </form>
      <p className="auth-footnote">
        Summarix 是开源项目，源码与部署说明见
        {" "}
        <a className="auth-footnote-link" href={REPOSITORY_URL} target="_blank" rel="noreferrer">
          GitHub
        </a>
        。
      </p>
    </div>
  );
}

function ChatView({
  resumeConversation,
  onResumed,
  setError,
  onAuthRequired,
  modelSettings,
  modelSettingsLoading,
  modelSettingsSaving,
  onModelSelectionChange
}: {
  resumeConversation: ConversationDetail | null;
  onResumed: () => void;
  setError: (value: string | null) => void;
  onAuthRequired: () => void;
  modelSettings: ModelSettings | null;
  modelSettingsLoading: boolean;
  modelSettingsSaving: boolean;
  onModelSelectionChange: (selection: { primary_model_id: string | null; primary_thinking_mode: ThinkingMode }) => Promise<boolean>;
}) {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [page, setPage] = useState<ExtractedPage | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTabInfo | null>(null);
  const [contextDirty, setContextDirty] = useState(false);
  const [contextNote, setContextNote] = useState<string | null>(null);
  const [contextSendMode, setContextSendMode] = useState<ContextSendMode | null>(null);
  const [drafts, setDrafts] = useState<DraftAttachment[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [modelPickerCloseTick, setModelPickerCloseTick] = useState(0);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const pageRef = useRef<ExtractedPage | null>(null);
  const activeTabRef = useRef<ActiveTabInfo | null>(null);
  const draftsRef = useRef<DraftAttachment[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const autoScrollRef = useRef(true);
  const nextAutoScrollBehaviorRef = useRef<MessageScrollBehavior | null>(null);
  const pendingScrollFrameRef = useRef<number | null>(null);
  const pendingScrollBehaviorRef = useRef<MessageScrollBehavior>("instant");
  const programmaticScrollUntilRef = useRef(0);
  const userScrollIntentRef = useRef(false);
  const userScrollIntentTimerRef = useRef<number | null>(null);
  const lastMessageCountRef = useRef(0);
  const lastMessageScrollTopRef = useRef(0);

  const pageStatus = useMemo(() => {
    if (extracting) return "正在读取当前网页";
    if (!page) return contextNote || "尚未读取网页正文";
    const title = page.title || activeTab?.title || "当前网页";
    return `${title} · ${pageLengthText(page)}`;
  }, [activeTab?.title, contextNote, extracting, page]);

  const hasContext = Boolean(page?.text || drafts.length > 0 || conversationId);
  const busy = sending || extracting || capturing || modelSettingsSaving;
  const tabLooksChanged = Boolean(page?.url && activeTab?.url && activeTab.url !== page.url);
  const pageNeedsRefresh = contextDirty || tabLooksChanged;
  const shouldAutoAttachFirstPage = !conversationId && messages.length === 0 && Boolean(page) && !pageNeedsRefresh;
  const selectedContextSendMode: ContextSendMode = contextSendMode ?? (shouldAutoAttachFirstPage ? "attachPage" : "followup");
  const attachContextLabel = pageNeedsRefresh ? "附新页" : "附当前页";

  function isMessageListNearBottom(element: HTMLDivElement): boolean {
    return element.scrollHeight - element.scrollTop - element.clientHeight <= AUTO_SCROLL_BOTTOM_THRESHOLD;
  }

  function scrollMessageListToBottom(behavior: MessageScrollBehavior) {
    const messageList = messageListRef.current;
    if (!messageList) return;
    programmaticScrollUntilRef.current = performance.now() + PROGRAMMATIC_SCROLL_LOCK_MS;
    messageList.scrollTo({ top: messageList.scrollHeight, behavior });
    lastMessageScrollTopRef.current = messageList.scrollTop;
  }

  function scheduleMessageListScroll(behavior: MessageScrollBehavior) {
    if (behavior === "smooth") pendingScrollBehaviorRef.current = "smooth";
    if (pendingScrollFrameRef.current !== null) return;
    pendingScrollFrameRef.current = window.requestAnimationFrame(() => {
      pendingScrollFrameRef.current = null;
      const nextBehavior = pendingScrollBehaviorRef.current;
      pendingScrollBehaviorRef.current = "instant";
      if (!autoScrollRef.current) return;
      scrollMessageListToBottom(nextBehavior);
    });
  }

  function enableAutoScrollOnNextRender(behavior: MessageScrollBehavior) {
    autoScrollRef.current = true;
    nextAutoScrollBehaviorRef.current = behavior;
  }

  function noteMessageListUserScrollIntent() {
    userScrollIntentRef.current = true;
    if (userScrollIntentTimerRef.current !== null) window.clearTimeout(userScrollIntentTimerRef.current);
    userScrollIntentTimerRef.current = window.setTimeout(() => {
      userScrollIntentRef.current = false;
      userScrollIntentTimerRef.current = null;
    }, USER_SCROLL_INTENT_MS);
  }

  function handleMessageListScroll() {
    const messageList = messageListRef.current;
    if (!messageList) return;
    const nextScrollTop = messageList.scrollTop;
    const userMovedUp = nextScrollTop < lastMessageScrollTopRef.current - 1;
    lastMessageScrollTopRef.current = nextScrollTop;
    if (isMessageListNearBottom(messageList)) {
      autoScrollRef.current = true;
      return;
    }
    const isProgrammaticScroll = performance.now() < programmaticScrollUntilRef.current && !userScrollIntentRef.current;
    if (isProgrammaticScroll) return;
    if (userMovedUp || userScrollIntentRef.current) autoScrollRef.current = false;
  }

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
    const previousMessageCount = lastMessageCountRef.current;
    lastMessageCountRef.current = messages.length;
    if (!autoScrollRef.current || messages.length === 0) {
      nextAutoScrollBehaviorRef.current = null;
      return;
    }
    const requestedBehavior = nextAutoScrollBehaviorRef.current;
    nextAutoScrollBehaviorRef.current = null;
    scheduleMessageListScroll(requestedBehavior ?? (messages.length > previousMessageCount ? "smooth" : "instant"));
  }, [messages]);

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
      if (pendingScrollFrameRef.current !== null) window.cancelAnimationFrame(pendingScrollFrameRef.current);
      if (userScrollIntentTimerRef.current !== null) window.clearTimeout(userScrollIntentTimerRef.current);
      abortRef.current?.abort();
      for (const draft of draftsRef.current) URL.revokeObjectURL(draft.previewUrl);
    };
  }, []);

  useEffect(() => {
    if (!resumeConversation) return;
    enableAutoScrollOnNextRender("instant");
    setConversationId(resumeConversation.id);
    setMessages(
      resumeConversation.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        persisted: true,
        traceId: message.trace_id || null,
        adkInvocationId: message.adk_invocation_id || null,
        artifacts: message.artifacts || [],
        feedback: message.feedback
          ? {
            id: message.feedback.id,
            rating: message.feedback.rating,
            pending: false,
            error: null,
            langwatchSyncStatus: message.feedback.langwatch_sync_status
          }
          : undefined
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
    setContextSendMode("followup");
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

  function clearDrafts() {
    setDrafts((items) => {
      for (const item of items) URL.revokeObjectURL(item.previewUrl);
      return [];
    });
  }

  function startNewChat() {
    if (sending) return;
    setError(null);
    enableAutoScrollOnNextRender("instant");
    setMessages([]);
    setConversationId(null);
    setInput("");
    setContextSendMode(null);
    clearDrafts();
    textareaRef.current?.focus();
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

  function applySuggestedQuestions(assistantId: string, questions: string[], fallbackId?: string) {
    const cleanedQuestions = questions.map((question) => question.trim()).filter(Boolean).slice(0, SUGGESTED_QUESTION_COUNT);
    setMessages((items) => items.map((item) => {
      if (item.id !== assistantId && item.id !== fallbackId) return item;
      return cleanedQuestions.length > 0
        ? { ...item, suggestedQuestions: cleanedQuestions, suggestionsVisible: true, suggestionsLoading: false }
        : { ...item, suggestedQuestions: undefined, suggestionsVisible: false, suggestionsLoading: false };
    }));
  }

  function revealSuggestionsLoading(assistantId: string, fallbackId?: string) {
    setMessages((items) => items.map((item) => (
      item.id === assistantId || item.id === fallbackId
        ? { ...item, suggestionsVisible: true, suggestionsLoading: true }
        : item
    )));
  }

  function finishSuggestions(assistantId: string, fallbackId?: string) {
    setMessages((items) => items.map((item) => {
      if (item.id !== assistantId && item.id !== fallbackId) return item;
      const hasSuggestedQuestions = (item.suggestedQuestions || []).length > 0;
      return { ...item, suggestionsVisible: hasSuggestedQuestions, suggestionsLoading: false };
    }));
  }

  function applyAdkEvent(assistantId: string, event: AdkEvent) {
    const errorMessage = getEventError(event);
    if (errorMessage) setError(errorMessage);
    if (event.interrupted) return;
    const answerText = getEventText(event, false);
    const thoughtText = getEventText(event, true);
    const turnComplete = getTurnComplete(event);
    const isPartial = event.partial === true;
    const invocationId = event.invocationId || event.invocation_id || null;
    if (!answerText && !thoughtText && !turnComplete) return;
    setMessages((items) => items.map((item) => {
      if (item.id !== assistantId) return item;
      const next = { ...item };
      if (invocationId && !next.adkInvocationId) next.adkInvocationId = invocationId;
      if (event.trace_id && !next.traceId) next.traceId = event.trace_id;
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

  async function handleFeedback(messageId: string, rating: FeedbackRating) {
    const target = messages.find((message) => message.id === messageId);
    if (!target || target.role !== "assistant" || target.persisted === false) return;
    const previous = target.feedback;
    setError(null);
    setMessages((items) => items.map((item) => (
      item.id === messageId
        ? { ...item, feedback: { ...item.feedback, rating, pending: true, error: null } }
        : item
    )));
    try {
      const response = await submitFeedback({
        messageId,
        rating,
        traceId: target.traceId || target.adkInvocationId || null
      });
      setMessages((items) => items.map((item) => (
        item.id === messageId
          ? {
            ...item,
            traceId: response.trace_id || item.traceId || null,
            feedback: {
              id: response.id,
              rating: response.rating,
              pending: false,
              error: response.langwatch_sync_error || null,
              langwatchSyncStatus: response.langwatch_sync_status
            }
          }
          : item
      )));
    } catch (error) {
      setMessages((items) => items.map((item) => (item.id === messageId ? { ...item, feedback: previous } : item)));
      if (isAuthRequiredError(error)) {
        onAuthRequired();
      } else {
        setError(error instanceof Error ? error.message : "反馈提交失败");
      }
    }
  }

  function getEffectiveContextSendMode(contextMode?: ContextSendMode): ContextSendMode {
    if (contextMode) return contextMode;
    if (contextSendMode) return contextSendMode;
    return !conversationId && messages.length === 0 && pageRef.current && !isRequestPageStale() ? "attachPage" : "followup";
  }

  function isRequestPageStale(): boolean {
    const currentPage = pageRef.current;
    const currentTab = activeTabRef.current;
    return contextDirty || Boolean(currentPage?.url && currentTab?.url && currentTab.url !== currentPage.url);
  }

  async function resolveRequestPage(contextMode: ContextSendMode): Promise<ExtractedPage | null | undefined> {
    if (contextMode === "followup") return null;
    if (pageRef.current && !isRequestPageStale()) return pageRef.current;
    if (extracting) {
      setError("正在读取网页，请稍候再发送");
      return undefined;
    }
    const nextPage = await extractPage();
    return nextPage || undefined;
  }

  async function sendPrompt(messageText = input.trim(), options: SendPromptOptions = {}) {
    const text = messageText.trim();
    if (!text || sending) return;
    if (modelSettingsLoading || modelSettingsSaving) {
      setError("模型设置正在同步，请稍候再发送");
      return;
    }
    setError(null);
    const contextMode = getEffectiveContextSendMode(options.contextMode);
    const requestPage = await resolveRequestPage(contextMode);
    if (requestPage === undefined) return;
    setSending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const assistantId = makeLocalId();
    let persistedAssistantId = assistantId;
    try {
      const draftSnapshot = [...drafts, ...(options.extraDrafts || [])];
      const pageReference = requestPage ? makePageReferenceAttachment(requestPage) : null;
      const uploadedArtifacts = await uploadDrafts(draftSnapshot);
      const userMessage: LocalMessage = {
        id: makeLocalId(),
        role: "user",
        content: text,
        persisted: false,
        artifacts: [...(pageReference ? [pageReference] : []), ...uploadedArtifacts]
      };
      enableAutoScrollOnNextRender("smooth");
      setMessages((items) => [
        ...items.map((item) => (item.role === "assistant" ? { ...item, suggestedQuestions: undefined, suggestionsVisible: false, suggestionsLoading: false } : item)),
        userMessage,
        { id: assistantId, role: "assistant", content: "", persisted: false, suggestionsVisible: false, suggestionsLoading: true }
      ]);
      setInput("");
      setDrafts([]);
      await streamChat({
        conversationId,
        message: text,
        context: requestPage ? { page_url: requestPage.url, page_title: requestPage.title, page_text: requestPage.text } : null,
        artifactIds: uploadedArtifacts.map((artifact) => artifact.id),
        signal: controller.signal,
        onConversation: (payload) => {
          setConversationId(payload.id);
          setMessages((items) => items.map((item) => (
            item.id === userMessage.id
              ? {
                ...item,
                id: payload.user_message_id || item.id,
                persisted: Boolean(payload.user_message_id),
                traceId: payload.trace_id || item.traceId || null,
                artifacts: mergeReferenceArtifacts(item.artifacts, payload.reference_artifacts || [])
              }
              : item.id === assistantId
                ? { ...item, traceId: payload.trace_id || item.traceId || null }
              : item
          )));
        },
        onAdkEvent: (event) => applyAdkEvent(assistantId, event),
        onPersisted: (payload) => {
          if (!payload.assistant_message_id) return;
          persistedAssistantId = payload.assistant_message_id;
          setMessages((items) => items.map((item) => (
            item.id === assistantId
              ? {
                ...item,
                id: payload.assistant_message_id || item.id,
                persisted: true,
                traceId: payload.trace_id || item.traceId || null,
                adkInvocationId: payload.adk_invocation_id || item.adkInvocationId || null
              }
              : item
          )));
        },
        onDone: () => {
          setSending(false);
          revealSuggestionsLoading(assistantId, persistedAssistantId);
          setContextSendMode("followup");
        },
        onSuggestedQuestions: (payload) => {
          applySuggestedQuestions(assistantId, payload.questions, persistedAssistantId);
        }
      });
    } catch (error) {
      if (isAbortError(error)) {
        setMessages((items) => items.map((item) => (item.id === assistantId && !item.content.trim() ? { ...item, content: "已停止生成。" } : item)));
      } else if (isAuthRequiredError(error)) {
        onAuthRequired();
      } else {
        setError(error instanceof Error ? error.message : "发送失败");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      finishSuggestions(assistantId, persistedAssistantId);
      setContextSendMode("followup");
      setSending(false);
    }
  }

  async function refreshSuggestions(messageId: string) {
    if (!conversationId) return;
    setError(null);
    setMessages((items) => items.map((item) => (item.id === messageId ? { ...item, suggestionsVisible: true, suggestionsLoading: true } : item)));
    try {
      await streamSuggestedQuestions({
        conversationId,
        assistantMessageId: messageId,
        count: SUGGESTED_QUESTION_COUNT,
        onSuggestedQuestions: (payload) => applySuggestedQuestions(messageId, payload.questions)
      });
    } catch (error) {
      if (isAuthRequiredError(error)) {
        onAuthRequired();
      } else {
        setError(error instanceof Error ? error.message : "建议问题生成失败");
      }
    } finally {
      finishSuggestions(messageId);
    }
  }

  async function runQuickAction(action: QuickAction) {
    const extraDrafts: DraftAttachment[] = [];
    const contextMode: ContextSendMode = action.needsPage
      ? "attachPage"
      : action.label === "继续追问"
        ? "followup"
        : contextSendMode === "attachPage"
          ? "attachPage"
          : "followup";
    if (action.needsScreenshot && drafts.length === 0) {
      const screenshot = await createScreenshotDraft();
      if (!screenshot) return;
      extraDrafts.push(screenshot);
    }
    await sendPrompt(action.prompt, { extraDrafts, contextMode });
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
      <div className="chat-toolbar">
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
        <button className="icon-button subtle new-chat-button" title="新建聊天" onClick={startNewChat} disabled={sending}>
          <Plus size={18} />
        </button>
      </div>

      <div
        className="message-list"
        ref={messageListRef}
        onScroll={handleMessageListScroll}
        onWheel={noteMessageListUserScrollIntent}
        onTouchMove={noteMessageListUserScrollIntent}
        onPointerDown={noteMessageListUserScrollIntent}
      >
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
            onAskSuggestedQuestion={(question) => void sendPrompt(question, { contextMode: "followup" })}
            onRefreshSuggestions={(id) => void refreshSuggestions(id)}
            onFeedback={(id, rating) => void handleFeedback(id, rating)}
          />
        ))}
      </div>

      {messages.length > 0 && <QuickActionGrid actions={QUICK_ACTIONS} compact disabled={busy} onAction={runQuickAction} />}
      {dragActive && <div className="drop-hint"><ImagePlus size={20} />松开即可添加图片</div>}
      {drafts.length > 0 && <DraftStrip drafts={drafts} onRemove={removeDraft} />}

      <div className="context-mode-row">
        <div className="context-mode-toggle" role="group" aria-label="下一条消息上下文">
          <button
            type="button"
            className={selectedContextSendMode === "followup" ? "active" : ""}
            title="下一条作为追问发送，不重新附加网页正文"
            onClick={() => setContextSendMode("followup")}
            disabled={sending}
          >
            <MessageSquare size={14} />
            追问
          </button>
          <button
            type="button"
            className={selectedContextSendMode === "attachPage" ? "active" : ""}
            title="下一条会读取并附加当前网页正文"
            onClick={() => setContextSendMode("attachPage")}
            disabled={sending}
          >
            <Link size={14} />
            {attachContextLabel}
          </button>
        </div>
      </div>

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
          onFocus={() => setModelPickerCloseTick((value) => value + 1)}
          onPaste={handlePaste}
          onKeyDown={handleComposerKeyDown}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入问题，Shift + Enter 换行"
          rows={1}
        />
        <ModelPicker
          settings={modelSettings}
          loading={modelSettingsLoading}
          saving={modelSettingsSaving}
          disabled={sending}
          closeSignal={modelPickerCloseTick}
          onChange={onModelSelectionChange}
        />
        {sending ? (
          <button className="icon-button send stop" title="停止生成" onClick={() => abortRef.current?.abort()}>
            <Square size={16} />
          </button>
        ) : (
          <button className="icon-button send" title="发送" onClick={() => void sendPrompt()} disabled={!input.trim() || modelSettingsLoading || modelSettingsSaving}>
            <Send size={18} />
          </button>
        )}
      </div>
    </section>
  );
}

function ModelIcon({ model, size = 18 }: { model?: AvailableModelOption | null; size?: number }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="model-icon" aria-hidden="true">
      {model?.icon_url && !failed ? (
        <img src={model.icon_url} alt="" onError={() => setFailed(true)} />
      ) : (
        <Sparkles size={size} />
      )}
    </span>
  );
}

function ModelPicker({
  settings,
  loading,
  saving,
  disabled,
  closeSignal,
  onChange
}: {
  settings: ModelSettings | null;
  loading: boolean;
  saving: boolean;
  disabled: boolean;
  closeSignal: number;
  onChange: (selection: { primary_model_id: string | null; primary_thinking_mode: ThinkingMode }) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [detailModelId, setDetailModelId] = useState<string | null>(null);
  const models = settings?.available_models ?? [];
  const selectedModel = models.find((model) => model.id === settings?.primary_model_id) ?? models[0] ?? null;
  const selectedThinkingMode = normalizeThinkingMode(settings?.primary_thinking_mode);
  const detailModel = detailModelId ? models.find((model) => model.id === detailModelId) ?? null : null;
  const label = selectedModel?.name || settings?.primary_model_id || "模型";
  const busy = loading || saving;

  function closeMenu() {
    setOpen(false);
    setDetailModelId(null);
  }

  useEffect(() => {
    if (closeSignal < 1) return;
    closeMenu();
  }, [closeSignal]);

  function toggleMenu() {
    setOpen((value) => {
      const nextOpen = !value;
      if (!nextOpen) setDetailModelId(null);
      return nextOpen;
    });
  }

  async function selectModel(model: AvailableModelOption) {
    const nextThinkingMode = model.id === settings?.primary_model_id
      ? selectedThinkingMode
      : normalizeThinkingMode(model.supports_thinking_config ? model.default_thinking_mode : "default");
    const saved = await onChange({ primary_model_id: model.id, primary_thinking_mode: nextThinkingMode });
    if (saved) {
      closeMenu();
    }
  }

  async function selectThinkingMode(model: AvailableModelOption, mode: ThinkingMode) {
    await onChange({ primary_model_id: model.id, primary_thinking_mode: mode });
  }

  return (
    <div className="model-picker">
      <button
        type="button"
        className="model-trigger"
        title="选择主力模型"
        onClick={toggleMenu}
        disabled={disabled || busy || models.length === 0}
      >
        {busy ? <Loader2 className="spin" size={15} /> : <ModelIcon model={selectedModel} size={15} />}
        <span>{label}</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="model-menu">
          {detailModel ? (
            <div className="model-detail-page">
              <div className="model-detail-header">
                <button
                  type="button"
                  className="model-detail-back"
                  title="返回模型列表"
                  onClick={() => setDetailModelId(null)}
                  disabled={saving}
                >
                  <ChevronLeft size={17} />
                </button>
                <div className="model-detail-title">
                  <ModelIcon model={detailModel} size={16} />
                  <span className="model-detail-copy">
                    <strong>{detailModel.name}</strong>
                    <span>{detailModel.description}</span>
                  </span>
                </div>
                {detailModel.id === selectedModel?.id ? (
                  <span className="model-badge current">当前</span>
                ) : detailModel.is_premium ? (
                  <span className="model-badge premium">高级</span>
                ) : null}
              </div>
              {detailModel.id !== selectedModel?.id && (
                <button type="button" className="model-use-button" onClick={() => void selectModel(detailModel)} disabled={saving}>
                  <Check size={15} />
                  使用此模型
                </button>
              )}
              <div className="model-detail-section">
                <div className="model-detail-section-heading">
                  <strong>思考模式</strong>
                </div>
                {detailModel.supports_thinking_config ? (
                  <div className="thinking-toggle model-thinking-toggle" role="group" aria-label={`${detailModel.name}思考模式`}>
                    {THINKING_MODE_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={detailModel.id === selectedModel?.id && selectedThinkingMode === option.value ? "active" : ""}
                        title={option.title}
                        onClick={() => void selectThinkingMode(detailModel, option.value)}
                        disabled={saving}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="model-fixed-thinking">默认</div>
                )}
              </div>
            </div>
          ) : (
            <div className="model-menu-list">
              {models.map((model) => {
                const active = model.id === selectedModel?.id;
                return (
                  <div className={`model-menu-row${active ? " active" : ""}`} key={model.id}>
                    <button type="button" className="model-option" onClick={() => void selectModel(model)} disabled={saving} aria-current={active ? "true" : undefined}>
                      <ModelIcon model={model} />
                      <span className="model-option-text">
                        <strong>{model.name}</strong>
                        <span>{model.description}</span>
                      </span>
                      <span className="model-badges">
                        {active ? <span className="model-badge current">当前</span> : model.is_premium && <span className="model-badge premium">高级</span>}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="model-detail-button"
                      title="模型设置"
                      aria-label={`${model.name}模型设置`}
                      onClick={() => setDetailModelId(model.id)}
                      disabled={saving}
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
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
  onToggleThought,
  onAskSuggestedQuestion,
  onRefreshSuggestions,
  onFeedback
}: {
  message: LocalMessage;
  streaming?: boolean;
  onToggleThought?: (id: string) => void;
  onAskSuggestedQuestion?: (question: string) => void;
  onRefreshSuggestions?: (id: string) => void;
  onFeedback?: (id: string, rating: FeedbackRating) => void;
}) {
  const hasThought = Boolean(message.thought?.trim());
  const suggestedQuestions = message.suggestedQuestions || [];
  const [copied, setCopied] = useState(false);
  const roleClass = message.role === "user" ? "user" : "assistant";
  const showSuggestions = roleClass === "assistant" && message.suggestionsVisible && (message.suggestionsLoading || suggestedQuestions.length > 0);
  const feedbackDisabled = streaming || message.persisted === false || message.feedback?.pending;

  async function copyMessage() {
    await copyText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <article className={`message ${roleClass}`}>
      {message.artifacts && message.artifacts.length > 0 && (
        <div className="message-attachments">
          {message.artifacts.map((artifact) => (
            artifact.source === "page_text"
              ? <ReferencePagePreview artifact={artifact} key={artifact.id} />
              : <AttachmentPreview artifact={artifact} key={artifact.id} />
          ))}
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
        {roleClass === "assistant" && message.content.trim() && (
          <>
            <button
              type="button"
              className={`ghost-action feedback-action${message.feedback?.rating === "like" ? " active" : ""}`}
              title="这条回答有帮助"
              disabled={feedbackDisabled}
              onClick={() => onFeedback?.(message.id, "like")}
            >
              <ThumbsUp size={13} />
            </button>
            <button
              type="button"
              className={`ghost-action feedback-action${message.feedback?.rating === "dislike" ? " active" : ""}`}
              title="这条回答需要改进"
              disabled={feedbackDisabled}
              onClick={() => onFeedback?.(message.id, "dislike")}
            >
              <ThumbsDown size={13} />
            </button>
          </>
        )}
      </div>
      {hasThought && roleClass === "assistant" && message.thoughtOpen && (
        <div className="thought-content">
          <MarkdownMessage content={message.thought || ""} />
        </div>
      )}
      {showSuggestions && (
        <div className="suggestions-panel" data-state={message.suggestionsLoading ? "loading" : "ready"}>
          <div className="suggestions-header">
            <span><Wand2 size={13} />下一步可以问</span>
            <button
              type="button"
              title="刷新建议问题"
              onClick={() => onRefreshSuggestions?.(message.id)}
              disabled={message.suggestionsLoading}
            >
              <RefreshCw className={message.suggestionsLoading ? "spin" : ""} size={13} />
            </button>
          </div>
          {!message.suggestionsLoading && suggestedQuestions.length > 0 ? (
            <div className="suggestion-chips">
              {suggestedQuestions.map((question) => (
                <button key={question} type="button" onClick={() => onAskSuggestedQuestion?.(question)}>
                  {question}
                </button>
              ))}
            </div>
          ) : (
            <div className="suggestions-loading"><TypingIndicator /></div>
          )}
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

function ReferencePagePreview({ artifact }: { artifact: MessageAttachment | Artifact }) {
  const title = getReferenceTitle(artifact);
  const source = getReferenceSource(artifact.page_url);
  const content = (
    <>
      <div className="reference-icon"><Link size={15} /></div>
      <div className="reference-copy">
        <strong title={title}>{title}</strong>
        <span title={artifact.page_url || source}>{source}</span>
        {artifact.text_excerpt && <p title={artifact.text_excerpt}>{artifact.text_excerpt}</p>}
        <small>{formatReferenceLength(artifact.text_length)}</small>
      </div>
    </>
  );
  if (artifact.page_url) {
    return <a className="reference-preview" href={artifact.page_url} target="_blank" rel="noreferrer">{content}</a>;
  }
  return <div className="reference-preview">{content}</div>;
}

function HistoryView({
  setError,
  onAuthRequired,
  onContinue
}: {
  setError: (value: string | null) => void;
  onAuthRequired: () => void;
  onContinue: (detail: ConversationDetail) => void;
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deleteConfirming, setDeleteConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

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
      if (!append) {
        setDetail(null);
        setDeleteConfirming(false);
      }
    } catch (error) {
      if (isAuthRequiredError(error)) onAuthRequired();
      else setError(error instanceof Error ? error.message : "加载历史失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function openDetail(id: string) {
    setError(null);
    setDeleteConfirming(false);
    try {
      setDetail(await getHistoryDetail(id));
    } catch (error) {
      if (isAuthRequiredError(error)) onAuthRequired();
      else setError(error instanceof Error ? error.message : "加载历史详情失败");
    }
  }

  async function confirmDelete() {
    if (!detail) return;
    const deletedId = detail.id;
    setDeleting(true);
    setError(null);
    try {
      await deleteHistory(deletedId);
      setItems((current) => current.filter((item) => item.id !== deletedId));
      setOffset((current) => Math.max(0, current - 1));
      setDetail((current) => (current?.id === deletedId ? null : current));
      setDeleteConfirming(false);
    } catch (error) {
      if (isAuthRequiredError(error)) onAuthRequired();
      else setError(error instanceof Error ? error.message : "删除历史失败");
    } finally {
      setDeleting(false);
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
                <div className="detail-title">
                  <strong>{detail.title}</strong>
                  <span>{detail.page_title || detail.page_url || "历史会话"}</span>
                </div>
                <div className="detail-actions">
                  <button onClick={() => onContinue(detail)} disabled={deleting}><MessageSquare size={15} />继续</button>
                  {deleteConfirming ? (
                    <>
                      <button onClick={() => setDeleteConfirming(false)} disabled={deleting}>取消</button>
                      <button className="danger-button" onClick={() => void confirmDelete()} disabled={deleting}>
                        <Trash2 size={15} />{deleting ? "删除中" : "确认删除"}
                      </button>
                    </>
                  ) : (
                    <button className="danger-button subtle" onClick={() => setDeleteConfirming(true)} disabled={deleting}>
                      <Trash2 size={15} />删除
                    </button>
                  )}
                </div>
              </div>
              <div className="history-messages">
                {detail.messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    message={{
                      id: message.id,
                      role: message.role,
                      content: message.content,
                      persisted: true,
                      traceId: message.trace_id || null,
                      adkInvocationId: message.adk_invocation_id || null,
                      artifacts: message.artifacts || [],
                      feedback: message.feedback
                        ? {
                          id: message.feedback.id,
                          rating: message.feedback.rating,
                          pending: false,
                          error: null,
                          langwatchSyncStatus: message.feedback.langwatch_sync_status
                        }
                        : undefined
                    }}
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

function normalizeThinkingMode(value?: string): ThinkingMode {
  if (value === "enabled" || value === "disabled") return value;
  return "default";
}

function SettingsView({
  setError,
  onAuthRequired,
  themePreference,
  resolvedTheme,
  onThemePreferenceChange,
  onThemePreferencePersisted,
  onLogout,
  logoutPending
}: {
  setError: (value: string | null) => void;
  onAuthRequired: () => void;
  themePreference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  onThemePreferenceChange: (value: ThemePreference) => void;
  onThemePreferencePersisted: (value: ThemePreference) => void;
  onLogout: () => void;
  logoutPending: boolean;
}) {
  const defaultApiBase = getDefaultApiBase();
  const [apiBaseValue, setApiBaseValue] = useState("");
  const [models, setModels] = useState<ModelSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const persistedThemeRef = useRef<ThemePreference>(themePreference);

  useEffect(() => {
    Promise.all([getApiBase(), getModelSettings()])
      .then(([base, modelSettings]) => {
        const nextThemePreference = normalizeThemePreference(modelSettings.theme);
        setApiBaseValue(base);
        setModels({ ...modelSettings, theme: nextThemePreference });
        persistedThemeRef.current = nextThemePreference;
        onThemePreferencePersisted(nextThemePreference);
      })
      .catch((error) => {
        if (isAuthRequiredError(error)) onAuthRequired();
        else setError(error instanceof Error ? error.message : "加载设置失败");
      });
  }, [onAuthRequired, onThemePreferencePersisted, setError]);

  function updateThemePreference(nextValue: ThemePreference) {
    setModels((value) => value && { ...value, theme: nextValue });
    onThemePreferenceChange(nextValue);
  }

  async function saveSettings() {
    if (!models) return;
    const normalizedApiBase = normalizeApiBaseInput(apiBaseValue);
    try {
      new URL(normalizedApiBase);
    } catch {
      setError("后端地址需要是完整 URL，例如 http://127.0.0.1:8000");
      return;
    }
    setLoading(true);
    setError(null);
    setSavedAt(null);
    try {
      await persistApiBasePreference(normalizedApiBase);
      setApiBaseValue(normalizedApiBase || defaultApiBase);
      const nextSettings = await updateModelSettings(models);
      const nextThemePreference = normalizeThemePreference(nextSettings.theme);
      setModels({ ...nextSettings, theme: nextThemePreference });
      persistedThemeRef.current = nextThemePreference;
      onThemePreferencePersisted(nextThemePreference);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (error) {
      const persistedThemePreference = persistedThemeRef.current;
      setModels((value) => value && { ...value, theme: persistedThemePreference });
      onThemePreferenceChange(persistedThemePreference);
      if (isAuthRequiredError(error)) onAuthRequired();
      else setError(error instanceof Error ? error.message : "保存设置失败");
    } finally {
      setLoading(false);
    }
  }

  const currentThemePreference = normalizeThemePreference(models?.theme ?? themePreference);

  return (
    <section className="settings-layout">
      <div className="settings-section">
        <div className="section-heading">
          <div>
            <strong>连接</strong>
            <span>侧边栏会通过这个地址访问 FastAPI 后端，恢复默认后保存即可生效。</span>
          </div>
          <button type="button" onClick={() => setApiBaseValue(defaultApiBase)}><RotateCcw size={15} />恢复默认</button>
        </div>
        <label>
          后端地址
          <input value={apiBaseValue} onChange={(event) => setApiBaseValue(event.target.value)} placeholder={defaultApiBase} />
        </label>
      </div>

      <div className="settings-section">
        <div className="section-heading">
          <div>
            <strong>外观</strong>
            <span>{currentThemePreference === "default" ? `跟随系统：${resolvedTheme === "dark" ? "深色" : "浅色"}` : "使用固定主题"}</span>
          </div>
        </div>
        <div className="theme-toggle" aria-label="外观主题">
          {THEME_OPTIONS.map((option) => {
            const Icon = option.icon;
            const active = currentThemePreference === option.value;
            return (
              <button
                key={option.value}
                type="button"
                className={active ? "active" : ""}
                onClick={() => updateThemePreference(option.value)}
                disabled={!models}
              >
                <Icon size={15} />
                {option.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="settings-section settings-footer">
        <div className="settings-footer-copy">
          <strong>应用更改</strong>
          <span>修改连接地址或主题后，点击保存设置即可生效。</span>
        </div>
        <div className="settings-footer-actions">
          {savedAt && <div className="save-state"><Check size={15} />已在 {savedAt} 保存</div>}
          <button className="primary-button" onClick={() => void saveSettings()} disabled={loading || !models}>
            {loading ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
            保存设置
          </button>
        </div>
      </div>

      <div className="settings-section settings-account-row">
        <div className="settings-account-copy">
          <strong>账户</strong>
          <span>需要时再重新登录即可。</span>
        </div>
        <button className="settings-logout-button" type="button" onClick={onLogout} disabled={logoutPending}>
          {logoutPending ? <Loader2 className="spin" size={16} /> : <LogOut size={16} />}
          退出登录
        </button>
      </div>
    </section>
  );
}

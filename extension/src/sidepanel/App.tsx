import { Camera, FileText, History, Loader2, LogIn, LogOut, MessageSquare, RefreshCw, Save, Send, Settings } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  getApiBase,
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
import type { Artifact, ConversationDetail, ConversationSummary, ExtractedPage, Message, ModelSettings, User } from "../shared/types";
import { captureVisibleTab, extractCurrentPage } from "./chrome";

type View = "chat" | "history" | "settings";

type LocalMessage = Pick<Message, "role" | "content"> & { id: string };

const HISTORY_PAGE_SIZE = 20;

function makeLocalId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function App() {
  const [user, setUser] = useState<User | null>(() => readCachedUser());
  const [view, setView] = useState<View>("chat");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    getMe().then(setUser).catch(() => setUser(null));
  }, []);

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
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const pageStatus = useMemo(() => {
    if (!page) return "未提取正文";
    return `${page.title || "当前网页"} · ${Math.round(page.text.length / 100) / 10}k 字`;
  }, [page]);

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

  async function captureAndUpload() {
    setError(null);
    setLoading(true);
    try {
      const dataUrl = await captureVisibleTab();
      const artifact = await uploadArtifact(dataUrl);
      setArtifacts((items) => [...items, artifact]);
    } catch (error) {
      setError(error instanceof Error ? error.message : "截图上传失败");
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage() {
    if (!input.trim()) return;
    setError(null);
    const userMessage: LocalMessage = { id: makeLocalId(), role: "user", content: input.trim() };
    const assistantId = makeLocalId();
    setMessages((items) => [...items, userMessage, { id: assistantId, role: "assistant", content: "" }]);
    setInput("");
    setLoading(true);
    try {
      await streamChat({
        conversationId,
        message: userMessage.content,
        context: page ? { page_url: page.url, page_title: page.title, page_text: page.text } : null,
        artifactIds: artifacts.map((artifact) => artifact.id),
        onConversation: setConversationId,
        onDelta: (text) => {
          setMessages((items) => items.map((item) => (item.id === assistantId ? { ...item, content: item.content + text } : item)));
        }
      });
      setArtifacts([]);
    } catch (error) {
      setError(error instanceof Error ? error.message : "发送失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="chat-layout">
      <div className="tool-row">
        <button title="提取正文" onClick={extractPage} disabled={loading}><FileText size={16} />正文</button>
        <button title="截图上传" onClick={captureAndUpload} disabled={loading}><Camera size={16} />截图</button>
        <span className="status-text">{pageStatus}</span>
      </div>

      <div className="message-list">
        {messages.length === 0 && <div className="empty-state">打开网页后提取正文或上传截图，然后直接提问。</div>}
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <div>{message.content || "..."}</div>
          </article>
        ))}
      </div>

      {artifacts.length > 0 && (
        <div className="artifact-strip">
          {artifacts.map((artifact) => <span key={artifact.id}>{artifact.filename}</span>)}
        </div>
      )}

      <div className="composer">
        <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入问题" rows={3} />
        <button className="icon-button send" title="发送" onClick={sendMessage} disabled={loading || !input.trim()}>
          {loading ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
        </button>
      </div>
    </section>
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

  return (
    <section className="history-layout">
      <div className="tool-row">
        <button onClick={() => load()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} />刷新</button>
      </div>
      <div className="history-grid">
        <div className="history-list">
          {items.map((item) => (
            <button key={item.id} className={detail?.id === item.id ? "selected" : ""} onClick={async () => setDetail(await getHistoryDetail(item.id))}>
              <strong>{item.title}</strong>
              <span>{new Date(item.updated_at).toLocaleString()}</span>
            </button>
          ))}
          {hasMore && <button onClick={() => load(offset, true)} disabled={loading}>加载更多</button>}
        </div>
        <div className="history-detail">
          {detail ? detail.messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>{message.content}</article>
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

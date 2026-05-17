import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  clearCachedUser: vi.fn().mockResolvedValue(undefined),
  clearRememberedAuth: vi.fn().mockResolvedValue(undefined),
  deleteHistory: vi.fn(),
  getApiBase: vi.fn().mockResolvedValue("https://stored.example.com"),
  getArtifactObjectUrl: vi.fn(),
  getDefaultApiBase: vi.fn(() => "https://compiled.example.com"),
  getHistoryDetail: vi.fn(),
  getMe: vi.fn(),
  getModelSettings: vi.fn(),
  isAuthRequiredError: vi.fn(() => false),
  listHistory: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  cacheModelSelection: vi.fn().mockResolvedValue(undefined),
  persistApiBasePreference: vi.fn().mockResolvedValue(undefined),
  persistRememberedAuth: vi.fn().mockResolvedValue(undefined),
  readCachedModelSelection: vi.fn().mockResolvedValue(null),
  readCachedUser: vi.fn().mockResolvedValue(null),
  readRememberedAuth: vi.fn().mockResolvedValue({
    email: "saved@example.com",
    password: "secret123",
    rememberEmail: true,
    rememberPassword: true
  }),
  register: vi.fn(),
  resetApiBase: vi.fn().mockResolvedValue(undefined),
  streamChat: vi.fn(),
  streamSuggestedQuestions: vi.fn(),
  submitFeedback: vi.fn(),
  updateModelSettings: vi.fn(),
  uploadArtifact: vi.fn()
}));

vi.mock("../shared/api", () => apiMocks);

import { App } from "./App";
import type { streamChat, streamSuggestedQuestions } from "../shared/api";

type StreamChatOptions = Parameters<typeof streamChat>[0];
type StreamSuggestedQuestionsOptions = Parameters<typeof streamSuggestedQuestions>[0];

const defaultModelSettings = {
  theme: "default",
  primary_model_id: "automatic",
  primary_thinking_mode: "default",
  available_models: [
    {
      id: "automatic",
      name: "Automatic",
      description: "模型会动态变化以使用最适合任务的模型",
      is_premium: false,
      icon_url: null,
      supports_thinking_config: true,
      default_thinking_mode: "default"
    },
    {
      id: "claude-sonnet",
      name: "Claude Sonnet",
      description: "搜索 · 视觉 · 工具",
      is_premium: true,
      icon_url: null,
      supports_thinking_config: false,
      default_thinking_mode: "default"
    }
  ],
  defaults: {
    primary_model_id: "automatic",
    primary_thinking_mode: "default",
    theme: "default"
  }
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getApiBase.mockResolvedValue("https://stored.example.com");
  apiMocks.getMe.mockResolvedValue(null);
  apiMocks.getModelSettings.mockResolvedValue(defaultModelSettings);
  apiMocks.listHistory.mockResolvedValue({ items: [], limit: 20, offset: 0, has_more: false });
  apiMocks.deleteHistory.mockResolvedValue(undefined);
  apiMocks.updateModelSettings.mockResolvedValue(defaultModelSettings);
  apiMocks.readCachedModelSelection.mockResolvedValue(null);
  apiMocks.readCachedUser.mockResolvedValue(null);
  apiMocks.cacheModelSelection.mockResolvedValue(undefined);
});

describe("sidepanel auth screen", () => {
  it("在登录页默认折叠连接设置，并展示记忆选项和开源说明", async () => {
    render(<App />);

    expect(await screen.findByText("登录到你的工作台")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("邮箱")).toHaveValue("saved@example.com"));

    expect(screen.getByLabelText("记住账号")).toBeChecked();
    expect(screen.getByLabelText("记住密码")).toBeChecked();
    expect(screen.queryByLabelText("后端地址")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /设置/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "设置" })).toHaveTextContent(/^设置$/);
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/GX-Swjtu/Summarix"
    );
  });

  it("点击设置可以展开和收起连接设置", async () => {
    render(<App />);

    const settingsToggle = await screen.findByRole("button", { name: /设置/ });
    expect(settingsToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(settingsToggle);

    expect(settingsToggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByLabelText("后端地址")).toBeInTheDocument();

    fireEvent.click(settingsToggle);

    await waitFor(() => expect(screen.queryByLabelText("后端地址")).not.toBeInTheDocument());
  });

  it("点击恢复默认会回到编译默认后端地址", async () => {
    render(<App />);

    const settingsToggle = await screen.findByRole("button", { name: /设置/ });
    fireEvent.click(settingsToggle);

    const apiBaseInput = await screen.findByLabelText("后端地址");
    await waitFor(() => expect(apiBaseInput).toHaveValue("https://stored.example.com"));

    fireEvent.click(screen.getByRole("button", { name: /恢复默认/ }));

    await waitFor(() => expect(apiMocks.resetApiBase).toHaveBeenCalled());
    expect(apiBaseInput).toHaveValue("https://compiled.example.com");
  });

  it("继续上次登录在没有可用登录态时会直接提示", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "继续上次登录" }));

    await waitFor(() => expect(apiMocks.getMe).toHaveBeenCalled());
    expect(await screen.findByText("当前没有可继续的登录状态，请直接登录。")).toBeInTheDocument();
  });
});

describe("sidepanel model picker", () => {
  it("在聊天输入框旁展示模型菜单，并保存用户选择", async () => {
    apiMocks.readCachedUser.mockResolvedValue({ id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" });
    apiMocks.updateModelSettings.mockResolvedValue({
      ...defaultModelSettings,
      primary_model_id: "claude-sonnet",
      primary_thinking_mode: "default"
    });

    render(<App />);

    const trigger = await screen.findByTitle("选择主力模型");
    await waitFor(() => expect(trigger).toHaveTextContent("Automatic"));

    fireEvent.click(trigger);
    expect(screen.getByText("模型会动态变化以使用最适合任务的模型")).toBeInTheDocument();

    const claudeOption = screen.getByText("Claude Sonnet").closest("button");
    expect(claudeOption).not.toBeNull();
    fireEvent.click(claudeOption!);

    await waitFor(() => expect(apiMocks.updateModelSettings).toHaveBeenCalledWith(expect.objectContaining({
      primary_model_id: "claude-sonnet",
      primary_thinking_mode: "default"
    })));
    await waitFor(() => expect(apiMocks.cacheModelSelection).toHaveBeenCalledWith({
      primary_model_id: "claude-sonnet",
      primary_thinking_mode: "default"
    }));
  });

  it("在模型详情页调整思考模式", async () => {
    apiMocks.readCachedUser.mockResolvedValue({ id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" });
    apiMocks.updateModelSettings.mockImplementation(async (nextSettings) => nextSettings);

    render(<App />);

    const trigger = await screen.findByTitle("选择主力模型");
    await waitFor(() => expect(trigger).toHaveTextContent("Automatic"));
    fireEvent.click(trigger);

    expect(screen.queryByRole("group", { name: "Automatic思考模式" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Automatic模型设置" }));

    const thinkingModeGroup = screen.getByRole("group", { name: "Automatic思考模式" });
    fireEvent.click(within(thinkingModeGroup).getByRole("button", { name: "开启" }));

    await waitFor(() => expect(apiMocks.updateModelSettings).toHaveBeenCalledWith(expect.objectContaining({
      primary_model_id: "automatic",
      primary_thinking_mode: "enabled"
    })));
    await waitFor(() => expect(apiMocks.cacheModelSelection).toHaveBeenLastCalledWith({
      primary_model_id: "automatic",
      primary_thinking_mode: "enabled"
    }));
  });

  it("展开模型菜单时切换箭头，并在输入框聚焦后自动收起", async () => {
    apiMocks.readCachedUser.mockResolvedValue({ id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" });

    render(<App />);

    const trigger = await screen.findByTitle("选择主力模型");
    await waitFor(() => expect(trigger).toHaveTextContent("Automatic"));
    expect(trigger.querySelector(".lucide-chevron-down")).not.toBeNull();

    fireEvent.click(trigger);

    expect(screen.getByText("模型会动态变化以使用最适合任务的模型")).toBeInTheDocument();
    expect(trigger.querySelector(".lucide-chevron-up")).not.toBeNull();

    fireEvent.focus(screen.getByPlaceholderText("输入问题，Shift + Enter 换行"));

    await waitFor(() => expect(screen.queryByText("模型会动态变化以使用最适合任务的模型")).not.toBeInTheDocument());
    expect(trigger.querySelector(".lucide-chevron-down")).not.toBeNull();
  });

  it("在设置页切换浅色主题时不会被未保存的服务端设置立刻覆盖", async () => {
    apiMocks.readCachedUser.mockResolvedValue({ id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "设置" }));
    expect(screen.queryByText(/编译默认值/)).not.toBeInTheDocument();

    const defaultThemeButton = await screen.findByRole("button", { name: "默认" });
    const lightThemeButton = screen.getByRole("button", { name: "浅色" });

    expect(defaultThemeButton).toHaveClass("active");
    expect(lightThemeButton).not.toHaveClass("active");
    expect(apiMocks.getModelSettings).toHaveBeenCalledTimes(2);

    fireEvent.click(lightThemeButton);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "浅色" })).toHaveClass("active");
      expect(screen.getByRole("button", { name: "默认" })).not.toHaveClass("active");
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(apiMocks.getModelSettings).toHaveBeenCalledTimes(2);
  });
});

describe("sidepanel history deletion", () => {
  const currentUser = { id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" };
  const summary = {
    id: "conversation-id",
    title: "会议纪要",
    page_url: "https://example.com/report",
    page_title: "季度报告",
    updated_at: "2026-05-18T00:20:00Z"
  };
  const detail = {
    ...summary,
    messages: [
      {
        id: "message-id",
        role: "assistant",
        content: "完整回复内容",
        trace_id: null,
        adk_invocation_id: null,
        created_at: "2026-05-18T00:20:00Z",
        artifacts: [],
        feedback: null
      }
    ],
    artifacts: []
  };

  it("在历史详情页确认删除后移除当前会话", async () => {
    apiMocks.readCachedUser.mockResolvedValue(currentUser);
    apiMocks.listHistory.mockResolvedValue({ items: [summary], limit: 20, offset: 0, has_more: false });
    apiMocks.getHistoryDetail.mockResolvedValue(detail);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "历史" }));
    fireEvent.click(await screen.findByRole("button", { name: /会议纪要/ }));
    expect(await screen.findByText("完整回复内容")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(apiMocks.deleteHistory).toHaveBeenCalledWith("conversation-id"));
    await waitFor(() => expect(screen.queryByText("完整回复内容")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /会议纪要/ })).not.toBeInTheDocument();
    expect(screen.getByText("选择一条历史记录")).toBeInTheDocument();
  });

  it("删除失败时保留当前详情并提示错误", async () => {
    apiMocks.readCachedUser.mockResolvedValue(currentUser);
    apiMocks.listHistory.mockResolvedValue({ items: [summary], limit: 20, offset: 0, has_more: false });
    apiMocks.getHistoryDetail.mockResolvedValue(detail);
    apiMocks.deleteHistory.mockRejectedValue(new Error("删除历史失败"));

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "历史" }));
    fireEvent.click(await screen.findByRole("button", { name: /会议纪要/ }));
    fireEvent.click(await screen.findByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByText("完整回复内容")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("删除历史失败");
  });
});

describe("sidepanel suggested questions", () => {
  it("主回答完成后才展开建议区，并在刷新时保持展开加载态", async () => {
    apiMocks.readCachedUser.mockResolvedValue({ id: "user-id", email: "tester@example.com", created_at: "2026-05-15T00:00:00Z" });

    let streamOptions: StreamChatOptions | null = null;
    let resolveStream: () => void = () => undefined;
    const streamPending = new Promise<void>((resolve) => {
      resolveStream = resolve;
    });
    apiMocks.streamChat.mockImplementation(async (options: StreamChatOptions) => {
      streamOptions = options;
      options.onConversation({ id: "conversation-id", user_message_id: "user-message-id" });
      await streamPending;
    });

    let refreshOptions: StreamSuggestedQuestionsOptions | null = null;
  let resolveRefresh: () => void = () => undefined;
    const refreshPending = new Promise<void>((resolve) => {
      resolveRefresh = resolve;
    });
    apiMocks.streamSuggestedQuestions.mockImplementation(async (options: StreamSuggestedQuestionsOptions) => {
      refreshOptions = options;
      await refreshPending;
    });

    render(<App />);

    const input = await screen.findByPlaceholderText("输入问题，Shift + Enter 换行");
    fireEvent.change(input, { target: { value: "帮我总结这页" } });
    await waitFor(() => expect(screen.getByTitle("发送")).not.toBeDisabled());
    fireEvent.click(screen.getByTitle("发送"));

    await waitFor(() => expect(apiMocks.streamChat).toHaveBeenCalled());
    expect(screen.queryByText("下一步可以问")).not.toBeInTheDocument();

    await act(async () => {
      streamOptions?.onAdkEvent({ content: { parts: [{ text: "主回答内容" }] } });
    });
    expect(await screen.findByText("主回答内容")).toBeInTheDocument();
    expect(screen.queryByText("下一步可以问")).not.toBeInTheDocument();

    await act(async () => {
      streamOptions?.onDone?.();
    });

    const loadingPanel = (await screen.findByText("下一步可以问")).closest(".suggestions-panel");
    expect(loadingPanel).toHaveAttribute("data-state", "loading");
    expect(screen.queryByRole("button", { name: "继续问题一" })).not.toBeInTheDocument();

    await act(async () => {
      streamOptions?.onSuggestedQuestions?.({ questions: ["  继续问题一  ", "继续问题二", "继续问题三"] });
    });

    expect(await screen.findByRole("button", { name: "继续问题一" })).toBeInTheDocument();
    expect(screen.getByText("下一步可以问").closest(".suggestions-panel")).toHaveAttribute("data-state", "ready");

    fireEvent.click(screen.getByTitle("刷新建议问题"));

    await waitFor(() => expect(apiMocks.streamSuggestedQuestions).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "conversation-id" })));
    expect(screen.getByText("下一步可以问").closest(".suggestions-panel")).toHaveAttribute("data-state", "loading");
    expect(screen.queryByRole("button", { name: "继续问题一" })).not.toBeInTheDocument();

    await act(async () => {
      refreshOptions?.onSuggestedQuestions({ questions: ["刷新后的问题"] });
    });

    expect(await screen.findByRole("button", { name: "刷新后的问题" })).toBeInTheDocument();
    expect(screen.getByText("下一步可以问").closest(".suggestions-panel")).toHaveAttribute("data-state", "ready");

    await act(async () => {
      resolveRefresh();
      resolveStream();
    });
  });
});
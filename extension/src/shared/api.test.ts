import { describe, expect, it, vi } from "vitest";

import {
  cacheModelSelection,
  getApiBase,
  getDefaultApiBase,
  persistApiBasePreference,
  persistRememberedAuth,
  readCachedModelSelection,
  readRememberedAuth,
  resetApiBase,
  updateModelSettings
} from "./api";

describe("shared api helpers", () => {
  it("优先使用用户覆盖的后端地址，并能恢复到编译默认值", async () => {
    expect(getDefaultApiBase()).toBe("https://compiled.example.com");
    await expect(getApiBase()).resolves.toBe("https://compiled.example.com");

    await persistApiBasePreference("https://override.example.com/");
    await expect(getApiBase()).resolves.toBe("https://override.example.com");

    await resetApiBase();
    await expect(getApiBase()).resolves.toBe("https://compiled.example.com");
  });

  it("记住密码时会一并记住账号，并在取消时清空本地记忆", async () => {
    await expect(readRememberedAuth()).resolves.toEqual({
      email: "",
      password: "",
      rememberEmail: true,
      rememberPassword: false
    });

    await persistRememberedAuth({
      email: " user@example.com ",
      password: "secret123",
      rememberEmail: false,
      rememberPassword: true
    });

    await expect(readRememberedAuth()).resolves.toEqual({
      email: "user@example.com",
      password: "secret123",
      rememberEmail: true,
      rememberPassword: true
    });

    await persistRememberedAuth({
      email: "user@example.com",
      password: "secret123",
      rememberEmail: false,
      rememberPassword: false
    });

    await expect(readRememberedAuth()).resolves.toEqual({
      email: "",
      password: "",
      rememberEmail: true,
      rememberPassword: false
    });
  });

  it("会缓存并读取主力模型选择", async () => {
    await expect(readCachedModelSelection()).resolves.toBeNull();

    await cacheModelSelection({ primary_model_id: "fast-model", primary_thinking_mode: "enabled" });

    await expect(readCachedModelSelection()).resolves.toEqual({
      primary_model_id: "fast-model",
      primary_thinking_mode: "enabled"
    });
  });

  it("更新模型设置时只提交主力模型和思考模式", async () => {
    const responsePayload = {
      theme: "dark",
      primary_model_id: "fast-model",
      primary_thinking_mode: "disabled",
      available_models: [],
      defaults: {}
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(responsePayload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(updateModelSettings({
      theme: "dark",
      primary_model_id: " fast-model ",
      primary_thinking_mode: "disabled"
    })).resolves.toEqual(responsePayload);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      theme: "dark",
      primary_model_id: "fast-model",
      primary_thinking_mode: "disabled"
    });
  });
});
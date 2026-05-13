import type { ActiveTabInfo, ExtractedPage } from "../shared/types";

type RuntimeResponse<T> = { ok: true } & T | { ok: false; error: string };

function sendRuntimeMessage<T>(message: object): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response: RuntimeResponse<T>) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "扩展内部请求失败"));
        return;
      }
      resolve(response as T);
    });
  });
}

export async function captureVisibleTab(): Promise<string> {
  const response = await sendRuntimeMessage<{ dataUrl: string }>({ type: "capture-visible-tab" });
  return response.dataUrl;
}

export async function extractCurrentPage(): Promise<ExtractedPage> {
  const response = await sendRuntimeMessage<{ page: ExtractedPage }>({ type: "extract-page" });
  return response.page;
}

export async function getActiveTabInfo(): Promise<ActiveTabInfo> {
  const response = await sendRuntimeMessage<{ tab: ActiveTabInfo }>({ type: "get-active-tab" });
  return response.tab;
}

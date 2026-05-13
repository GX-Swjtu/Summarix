import type { BackgroundRequest } from "../shared/types";

const CONTENT_SCRIPT_FILES = ["assets/content.js"];
const UNSUPPORTED_PAGE_PROTOCOLS = new Set(["about:", "chrome:", "chrome-extension:", "devtools:", "edge:", "moz-extension:"]);


function isMissingReceiverError(message: string | undefined): boolean {
  if (!message) {
    return false;
  }
  return /Could not establish connection|Receiving end does not exist/i.test(message);
}


function getPageProtocol(url: string | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    return new URL(url).protocol;
  } catch {
    return null;
  }
}


function getUnsupportedPageError(url: string | undefined): string | null {
  const protocol = getPageProtocol(url);
  if (!protocol) {
    return null;
  }
  if (UNSUPPORTED_PAGE_PROTOCOLS.has(protocol)) {
    return "当前页面不支持自动读取，请切换到普通网页后重试。";
  }
  return null;
}


function getReadableExtractError(url: string | undefined, error: unknown): string {
  const unsupportedError = getUnsupportedPageError(url);
  if (unsupportedError) {
    return unsupportedError;
  }
  const message = error instanceof Error ? error.message : String(error || "");
  if (isMissingReceiverError(message)) {
    return "当前页面暂时无法连接内容脚本，请刷新页面后重试。";
  }
  return message || "提取网页失败";
}


function sendMessageToTab<T>(tabId: number, message: object): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response: T) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}


function injectContentScript(tabId: number): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript({
      target: { tabId },
      files: CONTENT_SCRIPT_FILES,
    }, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve();
    });
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
});

chrome.runtime.onMessage.addListener((request: BackgroundRequest, _sender, sendResponse) => {
  if (request.type === "get-active-tab") {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab) {
        sendResponse({ ok: false, error: "没有可用的当前标签页" });
        return;
      }
      sendResponse({
        ok: true,
        tab: {
          id: tab.id,
          title: tab.title,
          url: tab.url,
        },
      });
    });
    return true;
  }

  if (request.type === "capture-visible-tab") {
    chrome.tabs.captureVisibleTab({ format: "png" }, (dataUrl) => {
      if (chrome.runtime.lastError || !dataUrl) {
        sendResponse({ ok: false, error: chrome.runtime.lastError?.message || "截图失败" });
        return;
      }
      sendResponse({ ok: true, dataUrl });
    });
    return true;
  }

  if (request.type === "extract-page") {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) {
        sendResponse({ ok: false, error: "没有可用的当前标签页" });
        return;
      }
      const unsupportedError = getUnsupportedPageError(tab.url);
      if (unsupportedError) {
        sendResponse({ ok: false, error: unsupportedError });
        return;
      }
      void (async () => {
        try {
          const response = await sendMessageToTab(tab.id!, { type: "extract-page" });
          sendResponse(response);
        } catch (error) {
          if (isMissingReceiverError(error instanceof Error ? error.message : undefined)) {
            try {
              await injectContentScript(tab.id!);
              const response = await sendMessageToTab(tab.id!, { type: "extract-page" });
              sendResponse(response);
              return;
            } catch (retryError) {
              sendResponse({ ok: false, error: getReadableExtractError(tab.url, retryError) });
              return;
            }
          }
          sendResponse({ ok: false, error: getReadableExtractError(tab.url, error) });
        }
      })();
    });
    return true;
  }

  return false;
});

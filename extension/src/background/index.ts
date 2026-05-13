import type { BackgroundRequest } from "../shared/types";

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
      chrome.tabs.sendMessage(tab.id, { type: "extract-page" }, (response) => {
        if (chrome.runtime.lastError) {
          sendResponse({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        sendResponse(response);
      });
    });
    return true;
  }

  return false;
});

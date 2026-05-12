import { Readability } from "@mozilla/readability";

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request.type !== "extract-page") {
    return false;
  }
  try {
    const documentClone = document.cloneNode(true) as Document;
    const article = new Readability(documentClone).parse();
    sendResponse({
      ok: true,
      page: {
        title: article?.title || document.title,
        url: location.href,
        text: article?.textContent || document.body.innerText || ""
      }
    });
  } catch (error) {
    sendResponse({ ok: false, error: error instanceof Error ? error.message : "提取网页正文失败" });
  }
  return true;
});

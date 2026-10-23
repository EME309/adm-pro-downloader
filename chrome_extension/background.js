const SERVER_URL = "http://127.0.0.1:47832/ext_add";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "adm_download_video",
      title: "🚀 دانلود ویدیو با ADM Pro",
      contexts: ["page", "link", "video"]
    });
    chrome.contextMenus.create({
      id: "adm_download_audio",
      title: "🎵 دانلود فقط صدا / موزیک (MP3) با ADM Pro",
      contexts: ["page", "link", "video", "audio"]
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const targetUrl = info.linkUrl || info.srcUrl || info.pageUrl;
  if (info.menuItemId === "adm_download_video") {
    sendToApp({
      url: targetUrl,
      title: (tab && tab.title) ? tab.title : "Video",
      action: "download",
      quality: "best"
    });
  } else if (info.menuItemId === "adm_download_audio") {
    sendToApp({
      url: targetUrl,
      title: (tab && tab.title) ? tab.title : "Audio",
      action: "download",
      quality: "audio"
    });
  }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "SEND_TO_ADM") {
    const payload = { ...request.payload };

    if (sender && sender.tab) {
      if (payload.useTabUrl && sender.tab.url) {
        payload.url = sender.tab.url;
      }
      if ((!payload.title || payload.title === "فایل دانلودی") && sender.tab.title) {
        payload.title = sender.tab.title;
      }
    }

    sendToApp(payload)
      .then((res) => sendResponse(res))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
});

async function sendToApp(payload) {
  try {
    const response = await fetch(SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return await response.json();
  } catch (error) {
    return { ok: false, error: "نرم‌افزار ADM Pro در ویندوز باز نیست!" };
  }
}
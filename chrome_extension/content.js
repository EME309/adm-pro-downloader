let floatingBtn = null;
let currentVideo = null;
let hideTimeout = null;
let isHoveringBtn = false;

function createButton() {
  if (floatingBtn) return;

  floatingBtn = document.createElement("div");
  floatingBtn.id = "adm-pro-floating-btn";
  floatingBtn.innerHTML = `
    <span id="adm-btn-direct" title="افزودن و شروع فوری دانلود با بهترین کیفیت">⬇️ دانلود با ADM Pro</span>
    <span id="adm-btn-queue" title="افزودن به لیست دانلود (بدون شروع خودکار)">➕</span>
    <span id="adm-btn-analyze" title="ارسال به بخش تحلیل برنامه برای انتخاب کیفیت">⚙️</span>
  `;

  Object.assign(floatingBtn.style, {
    position: "fixed",
    zIndex: "2147483647",
    display: "none",
    alignItems: "center",
    gap: "8px",
    background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
    color: "#ffffff",
    padding: "7px 14px",
    borderRadius: "8px",
    fontFamily: "Tahoma, Arial, sans-serif",
    fontSize: "12px",
    fontWeight: "bold",
    boxShadow: "0 4px 16px rgba(0,0,0,0.6)",
    border: "1px solid rgba(255,255,255,0.25)",
    cursor: "pointer",
    userSelect: "none",
    direction: "rtl",
    pointerEvents: "auto",
    transition: "opacity 0.15s ease"
  });

  const subBtnStyle = {
    paddingRight: "8px",
    borderRight: "1px solid rgba(255,255,255,0.35)",
    fontSize: "13px",
    display: "inline-flex",
    alignItems: "center"
  };

  const queueSpan = floatingBtn.querySelector("#adm-btn-queue");
  const analyzeSpan = floatingBtn.querySelector("#adm-btn-analyze");
  Object.assign(queueSpan.style, subBtnStyle);
  Object.assign(analyzeSpan.style, subBtnStyle);

  floatingBtn.addEventListener("mouseenter", () => {
    isHoveringBtn = true;
    clearTimeout(hideTimeout);
  });

  floatingBtn.addEventListener("mouseleave", () => {
    isHoveringBtn = false;
    scheduleHide(800);
  });

  floatingBtn.querySelector("#adm-btn-direct").addEventListener("click", (e) => {
    e.stopPropagation(); e.preventDefault();
    triggerSend("download", true);
  });

  queueSpan.addEventListener("click", (e) => {
    e.stopPropagation(); e.preventDefault();
    triggerSend("download", false);
  });

  analyzeSpan.addEventListener("click", (e) => {
    e.stopPropagation(); e.preventDefault();
    triggerSend("analyze", true);
  });

  (document.body || document.documentElement).appendChild(floatingBtn);
}

function getAllVideos(root = document) {
  const videos = Array.from(root.querySelectorAll("video"));
  const allElements = root.querySelectorAll("*");
  for (const el of allElements) {
    if (el.shadowRoot) {
      videos.push(...getAllVideos(el.shadowRoot));
    }
  }
  return videos;
}

function resolveVideoPayload(videoEl) {
  const pageUrl = window.location.href;
  let src = videoEl.currentSrc || videoEl.src || "";
  if (!src) {
    const sourceTag = videoEl.querySelector("source");
    if (sourceTag) src = sourceTag.src || "";
  }
  const isDirectFile = /\.(mp4|mkv|webm|mov)(\?|$)/i.test(src) && !src.includes("blob:");
  const isInsideIframe = window !== window.top;

  return {
    url: isDirectFile ? src : pageUrl,
    useTabUrl: !isDirectFile || isInsideIframe,
    title: document.title || "ویدیو دانلودی"
  };
}

function triggerSend(actionType, startNow = true) {
  if (!currentVideo || !floatingBtn) return;

  const info = resolveVideoPayload(currentVideo);
  const directText = floatingBtn.querySelector("#adm-btn-direct");
  const originalLabel = "⬇️ دانلود با ADM Pro";

  directText.textContent = "⏳ در حال ارسال...";

  chrome.runtime.sendMessage(
    {
      type: "SEND_TO_ADM",
      payload: {
        url: info.url,
        useTabUrl: info.useTabUrl,
        title: info.title,
        action: actionType,
        start_now: startNow,
        quality: "best"
      }
    },
    (res) => {
      if (res && res.ok) {
        floatingBtn.style.background = "linear-gradient(135deg, #16a34a, #15803d)";
        if (actionType === "analyze") directText.textContent = "✅ در بخش تحلیل باز شد!";
        else if (startNow) directText.textContent = "✅ دانلود شروع شد!";
        else directText.textContent = "📌 به لیست انتظار اضافه شد!";
      } else {
        floatingBtn.style.background = "linear-gradient(135deg, #dc2626, #b91c1c)";
        directText.textContent = "❌ برنامه ADM باز نیست!";
      }

      setTimeout(() => {
        if (floatingBtn) {
          floatingBtn.style.background = "linear-gradient(135deg, #2563eb, #1d4ed8)";
          directText.textContent = originalLabel;
        }
      }, 2500);
    }
  );
}

function positionButtonOnVideo(video) {
  const rect = video.getBoundingClientRect();
  if (rect.width < 160 || rect.height < 100) return false;
  if (rect.bottom < 0 || rect.top > window.innerHeight) return false;

  createButton();
  currentVideo = video;
  clearTimeout(hideTimeout);

  floatingBtn.style.top = `${Math.max(12, rect.top + 14)}px`;
  floatingBtn.style.left = `${Math.max(12, rect.left + 14)}px`;
  floatingBtn.style.display = "flex";
  return true;
}

function scheduleHide(delay = 1200) {
  clearTimeout(hideTimeout);
  hideTimeout = setTimeout(() => {
    if (floatingBtn && !isHoveringBtn) floatingBtn.style.display = "none";
  }, delay);
}

let lastCheck = 0;
window.addEventListener("mousemove", (e) => {
  const now = Date.now();
  if (now - lastCheck < 80 || isHoveringBtn) return;
  lastCheck = now;

  const x = e.clientX, y = e.clientY;
  for (const v of getAllVideos()) {
    const r = v.getBoundingClientRect();
    if (r.width >= 160 && r.height >= 100 && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
      positionButtonOnVideo(v);
      return;
    }
  }
  scheduleHide(1000);
}, { passive: true, capture: true });

document.addEventListener("play", (e) => {
  if (e.target && e.target.tagName === "VIDEO" && positionButtonOnVideo(e.target)) {
    scheduleHide(3500);
  }
}, true);

window.addEventListener("scroll", () => {
  if (floatingBtn && floatingBtn.style.display === "flex" && currentVideo) {
    positionButtonOnVideo(currentVideo);
  }
}, { passive: true });
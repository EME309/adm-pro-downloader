let floatingBtn = null;
let currentMedia = null;
let hideTimeout = null;
let isHoveringBtn = false;

function createButton() {
  if (floatingBtn) return;

  floatingBtn = document.createElement("div");
  floatingBtn.id = "adm-pro-floating-btn";
  floatingBtn.innerHTML = `
    <span id="adm-btn-direct" title="دانلود ویدیو با بهترین کیفیت">⬇️ ویدیو</span>
    <span id="adm-btn-audio" title="دانلود فقط موزیک / صدا با فرمت MP3">🎵 MP3</span>
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
    padding: "7px 12px",
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

  const audioSpan = floatingBtn.querySelector("#adm-btn-audio");
  Object.assign(audioSpan.style, {
    paddingRight: "8px",
    borderRight: "1px solid rgba(255,255,255,0.35)",
    color: "#fde047"
  });

  const analyzeSpan = floatingBtn.querySelector("#adm-btn-analyze");
  Object.assign(analyzeSpan.style, {
    paddingRight: "8px",
    borderRight: "1px solid rgba(255,255,255,0.35)",
    fontSize: "14px",
    display: "inline-flex",
    alignItems: "center"
  });

  floatingBtn.addEventListener("mouseenter", () => {
    isHoveringBtn = true;
    clearTimeout(hideTimeout);
  });

  floatingBtn.addEventListener("mouseleave", () => {
    isHoveringBtn = false;
    scheduleHide(800);
  });

  floatingBtn.querySelector("#adm-btn-direct").addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    triggerSend("download", "best");
  });

  audioSpan.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    triggerSend("download", "audio");
  });

  analyzeSpan.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    triggerSend("analyze", "best");
  });

  (document.body || document.documentElement).appendChild(floatingBtn);
}

function getAllMedia(root = document) {
  const media = Array.from(root.querySelectorAll("video, audio"));
  const allElements = root.querySelectorAll("*");
  for (const el of allElements) {
    if (el.shadowRoot) {
      media.push(...getAllMedia(el.shadowRoot));
    }
  }
  return media;
}

function resolveMediaPayload(mediaEl) {
  const pageUrl = window.location.href;
  let src = mediaEl.currentSrc || mediaEl.src || "";

  if (!src) {
    const sourceTag = mediaEl.querySelector("source");
    if (sourceTag) src = sourceTag.src || "";
  }

  const isDirectFile = /\.(mp4|mkv|webm|mov|mp3|m4a|flac|wav|ogg|aac)(\?|$)/i.test(src) && !src.includes("blob:");
  const isInsideIframe = window !== window.top;

  return {
    url: isDirectFile ? src : pageUrl,
    useTabUrl: !isDirectFile || isInsideIframe,
    title: document.title || "فایل دانلودی"
  };
}

function triggerSend(actionType, qualityType) {
  if (!currentMedia || !floatingBtn) return;

  const info = resolveMediaPayload(currentMedia);
  const directText = floatingBtn.querySelector("#adm-btn-direct");

  directText.textContent = "⏳ ارسال...";

  chrome.runtime.sendMessage(
    {
      type: "SEND_TO_ADM",
      payload: {
        url: info.url,
        useTabUrl: info.useTabUrl,
        title: info.title,
        action: actionType,
        quality: qualityType
      }
    },
    (res) => {
      if (res && res.ok) {
        floatingBtn.style.background = "linear-gradient(135deg, #16a34a, #15803d)";
        directText.textContent = qualityType === "audio" ? "✅ MP3 در صف!" : "✅ در صف دانلود!";
      } else {
        floatingBtn.style.background = "linear-gradient(135deg, #dc2626, #b91c1c)";
        directText.textContent = "❌ برنامه باز نیست!";
      }

      setTimeout(() => {
        if (floatingBtn) {
          floatingBtn.style.background = "linear-gradient(135deg, #2563eb, #1d4ed8)";
          directText.textContent = "⬇️ ویدیو";
        }
      }, 2500);
    }
  );
}

function positionButtonOnMedia(mediaEl) {
  createButton();
  currentMedia = mediaEl;
  clearTimeout(hideTimeout);

  const rect = mediaEl.getBoundingClientRect();

  // اگر تگ صوتی (<audio>) مخفی یا خیلی کوچک بود، دکمه را در گوشه پایین-چپ صفحه نشان بده
  if (mediaEl.tagName === "AUDIO" && (rect.width < 100 || rect.height < 25)) {
    floatingBtn.style.top = `${window.innerHeight - 60}px`;
    floatingBtn.style.left = "20px";
    floatingBtn.style.display = "flex";
    return true;
  }

  if (rect.width < 160 || rect.height < 40) return false;
  if (rect.bottom < 0 || rect.top > window.innerHeight) return false;

  const topPos = Math.max(12, rect.top + 14);
  const leftPos = Math.max(12, rect.left + 14);

  floatingBtn.style.top = `${topPos}px`;
  floatingBtn.style.left = `${leftPos}px`;
  floatingBtn.style.display = "flex";
  return true;
}

function scheduleHide(delay = 1200) {
  clearTimeout(hideTimeout);
  hideTimeout = setTimeout(() => {
    if (floatingBtn && !isHoveringBtn) {
      floatingBtn.style.display = "none";
    }
  }, delay);
}

let lastCheck = 0;
window.addEventListener("mousemove", (e) => {
  const now = Date.now();
  if (now - lastCheck < 80) return;
  lastCheck = now;

  if (isHoveringBtn) return;

  const x = e.clientX;
  const y = e.clientY;
  const mediaList = getAllMedia();

  let matched = null;
  for (const m of mediaList) {
    const r = m.getBoundingClientRect();
    const minH = m.tagName === "AUDIO" ? 25 : 100;
    if (r.width >= 150 && r.height >= minH) {
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
        matched = m;
        break;
      }
    }
  }

  if (matched) {
    positionButtonOnMedia(matched);
  } else {
    scheduleHide(1000);
  }
}, { passive: true, capture: true });

// به محض پخش شدن هر ویدیو یا موزیک (<audio>) در صفحه، دکمه دانلود ظاهر شود
document.addEventListener("play", (e) => {
  if (e.target && (e.target.tagName === "VIDEO" || e.target.tagName === "AUDIO")) {
    if (positionButtonOnMedia(e.target)) {
      scheduleHide(4000);
    }
  }
}, true);

window.addEventListener("scroll", () => {
  if (floatingBtn && floatingBtn.style.display === "flex" && currentMedia) {
    positionButtonOnMedia(currentMedia);
  }
}, { passive: true });
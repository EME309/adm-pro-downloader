# -*- coding: utf-8 -*-
"""
ADM Pro Downloader - نسخه ۲
-----------------------------------------------------------
تغییرات اصلی نسبت به نسخه قبل:
  1) سیستم مدیریت خطا: همه خطاها (حتی خطاهای داخل نخ‌ها و رابط گرافیکی)
     در فایل logs/app.log و ترمینال ثبت می‌شوند و در برنامه دسته‌بندی می‌شوند.
  2) دکمه «گزارش برای پشتیبان» که همه‌چیز لازم برای عیب‌یابی را کپی می‌کند.
  3) رفع علت‌های رایج خطای دانلود: نبودن ffmpeg، نبودن JS runtime برای یوتیوب،
     خطاهای بلعیده‌شده، و رقابت بین نخ‌های صف دانلود.
-----------------------------------------------------------
"""
import os
import sys
import re
import json
import uuid
import time
import shutil
import socket
import platform
import functools
import threading
import traceback
import logging
import webbrowser
import subprocess
import importlib.util
import importlib.metadata
from collections import deque, Counter
from datetime import datetime
from logging.handlers import RotatingFileHandler

APP_VERSION = "2.0"

# مسیرها: همیشه نسبت به پوشه‌ی خود برنامه (حتی وقتی با VBS یا میان‌بر اجرا می‌شود)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
LOG_DIR = os.path.join(BASE_DIR, "logs")
BIN_DIR = os.path.join(BASE_DIR, "bin")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
os.makedirs(LOG_DIR, exist_ok=True)

# خروجی ترمینال را UTF-8 می‌کنیم تا متن فارسی خراب نشود
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ======================================================================
#  لاگ: هم در فایل، هم در ترمینال، هم در حافظه (برای گزارش)
# ======================================================================
class MemoryHandler(logging.Handler):
    """آخرین پیام‌های لاگ را برای ساخت گزارش در حافظه نگه می‌دارد"""

    def __init__(self, capacity=400):
        super().__init__(level=logging.INFO)
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        try:
            self.buffer.append(self.format(record))
        except Exception:
            pass


log = logging.getLogger("adm")
log.setLevel(logging.DEBUG)
log.propagate = False
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"), maxBytes=1_500_000, backupCount=3, encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(_fmt)
log.addHandler(_file_handler)

if sys.stderr is not None:  # در حالت بی‌صدا (pythonw) ممکن است وجود نداشته باشد
    _console = logging.StreamHandler(sys.stderr)
    _console.setLevel(logging.INFO)
    _console.setFormatter(_fmt)
    log.addHandler(_console)

memlog = MemoryHandler()
memlog.setFormatter(_fmt)
log.addHandler(memlog)


def show_fatal(title, text):
    """نمایش پیام خطا حتی وقتی برنامه بدون پنجره‌ی ترمینال اجرا شده است"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        pass


# وارد کردن کتابخانه‌های اصلی: اگر نصب نباشند، به جای بسته‌شدن بی‌صدا پیام می‌دهیم
try:
    import eel
    import yt_dlp
    from yt_dlp.version import __version__ as YTDLP_VERSION
except Exception:
    log.critical("وارد کردن کتابخانه‌ها شکست خورد:\n%s", traceback.format_exc())
    show_fatal(
        "ADM Pro",
        "کتابخانه‌های لازم نصب نیستند.\n\nفایل start.bat را اجرا کنید تا نصب شوند.\n"
        "جزئیات: logs\\app.log",
    )
    sys.exit(1)


# ======================================================================
#  تنظیمات
# ======================================================================
def _default_save_path():
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return downloads if os.path.isdir(downloads) else BASE_DIR


ALLOWED_BROWSERS = ["", "firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium"]


def load_config():
    cfg = {"save_path": _default_save_path(), "cookies_browser": ""}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("فایل تنظیمات خوانده نشد؛ از مقادیر پیش‌فرض استفاده می‌شود")
    return cfg


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
    except Exception:
        log.exception("ذخیره‌ی تنظیمات انجام نشد")


config_data = load_config()


# ======================================================================
#  ابزارهای کمکی
# ======================================================================
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def clean(text):
    """حذف کدهای رنگی ترمینال و فاصله‌های اضافه"""
    return ANSI_RE.sub("", str(text)).strip()


def fmt_speed(bps):
    if not bps:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / 1048576:.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def fmt_eta(sec):
    if sec is None:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ui(fn_name, *args):
    """
    ارسال دستور به رابط گرافیکی (بدون منتظر ماندن برای پاسخ).
    اگر پنجره بسته شده باشد خطایی ایجاد نمی‌شود.
    """
    try:
        getattr(eel, fn_name)(*args)
    except Exception as e:
        log.debug("ui call %s failed: %s", fn_name, e)


# ======================================================================
#  دسته‌بندی خطاها: متن خام yt-dlp -> دلیل قابل فهم + راه‌حل
# ======================================================================
# هر مورد: (کد, الگوی جستجو, عنوان, راه‌حل). اولین موردی که تطابق بدهد انتخاب می‌شود.
ERROR_RULES = [
    ("bot", r"sign in to confirm|not a bot|confirm you.?re not",
     "سایت درخواست تأیید هویت (ضدربات) داده است",
     "در «تنظیمات پیشرفته» مرورگری را که در آن وارد حساب شده‌اید برای کوکی انتخاب کنید "
     "(Firefox پایدارتر است). اگر VPN روشن است، خاموش یا عوض کنید."),
    ("age", r"age.?restrict|confirm your age|inappropriate for some users",
     "ویدیو محدودیت سنی دارد",
     "کوکی مرورگری که در آن وارد حساب شده‌اید را در «تنظیمات پیشرفته» انتخاب کنید."),
    ("private", r"private video|members.?only|join this channel|this video is private|login required|"
                r"requires login|sign in to view|please sign in",
     "ویدیو خصوصی است یا فقط برای اعضا قابل مشاهده است",
     "فقط با حسابی که دسترسی دارد قابل دانلود است. کوکی مرورگر را در «تنظیمات پیشرفته» فعال کنید."),
    ("geo", r"not available in your country|geo.?restrict|blocked it in your country|georestrict",
     "این ویدیو در کشور شما در دسترس نیست",
     "با VPN به کشور دیگری وصل شوید و دوباره امتحان کنید."),
    ("unavailable", r"video unavailable|this video is (unavailable|no longer available)|has been removed|"
                    r"account associated .{0,60}terminated|video (was )?deleted",
     "ویدیو حذف شده یا دیگر در دسترس نیست",
     "لینک را در مرورگر باز کنید و مطمئن شوید هنوز وجود دارد."),
    ("unsupported", r"unsupported url|no suitable extractor|not a valid url",
     "این لینک پشتیبانی نمی‌شود یا نامعتبر است",
     "لینک کامل صفحه‌ی ویدیو را (با https://) وارد کنید."),
    ("rate", r"http error 429|too many requests",
     "سایت به‌خاطر درخواست‌های زیاد موقتاً دسترسی را بسته است (429)",
     "چند دقیقه صبر کنید یا با VPN/IP دیگری امتحان کنید."),
    ("forbidden", r"http error 403|forbidden",
     "سرور دسترسی را رد کرد (403)",
     "start.bat را اجرا کنید تا yt-dlp بروز شود، مطمئن شوید Deno نصب است، "
     "یا کوکی مرورگر را در «تنظیمات پیشرفته» فعال کنید."),
    ("disk", r"no space left|permission denied|winerror 5|access is denied|errno 13|errno 28|"
             r"file name too long|errno 22|invalid argument",
     "نوشتن فایل در مسیر ذخیره ممکن نیست",
     "مسیر ذخیره را عوض کنید و از آزاد بودن فضای دیسک و دسترسی نوشتن مطمئن شوید."),
    ("network", r"getaddrinfo failed|name resolution|timed out|timeout|connection (reset|refused|aborted)|"
                r"network is unreachable|unable to download (webpage|json|api)|ssl error|"
                r"certificate verify|proxy|remote end closed|incompleteread|temporary failure",
     "ارتباط با اینترنت یا سرور برقرار نشد",
     "اتصال اینترنت و VPN را بررسی کنید و دوباره امتحان کنید. اگر فقط یک سایت باز نمی‌شود، "
     "احتمالاً فیلتر است."),
    ("ffmpeg", r"ffmpeg.{0,40}(not (found|installed)|is not)|ffprobe.{0,40}not|you have requested merging|"
               r"ffmpeg not found",
     "ابزار ffmpeg پیدا نشد (برای ادغام تصویر و صدا لازم است)",
     "start.bat را یک‌بار دیگر اجرا کنید تا ffmpeg نصب شود."),
    ("js", r"javascript runtime|js runtime|n challenge|nsig|signature (solving|extraction)|"
           r"challenge solving|yt-dlp-ejs",
     "برای یوتیوب، موتور جاوااسکریپت (Deno) لازم است و پیدا نشد",
     "Deno را نصب کنید (دستور: winget install DenoLand.Deno یا اجرای start.bat) و برنامه را دوباره باز کنید."),
    ("format", r"requested format is not available|no video formats found|only images are available|no formats",
     "کیفیت یا فرمت درخواستی موجود نیست",
     "کیفیت را روی «بهترین» بگذارید. اگر ادامه داشت، Deno و بروز بودن yt-dlp را بررسی کنید."),
]
_COMPILED_RULES = [(c, re.compile(p, re.I | re.S), t, h) for c, p, t, h in ERROR_RULES]
UNKNOWN_ERROR = ("unknown", "خطای ناشناخته",
                 "دکمه «گزارش برای پشتیبان» را بزنید و متن کپی‌شده را بفرستید تا بررسی شود.")


def classify(text):
    text = clean(text)
    for code, rx, title, hint in _COMPILED_RULES:
        if rx.search(text):
            return {"code": code, "title": title, "hint": hint}
    return {"code": UNKNOWN_ERROR[0], "title": UNKNOWN_ERROR[1], "hint": UNKNOWN_ERROR[2]}


# رویدادهای خطا (برای تب «خطاها»)
error_events = deque(maxlen=60)
events_lock = threading.Lock()


def record_event(where, raw, url="", item="", extra="", tb=""):
    """
    ثبت یک خطا: در لاگ می‌نویسد، دسته‌بندی می‌کند و به رابط گرافیکی می‌فرستد.
    where: analyze | download | python | js
    """
    raw = clean(raw)
    cls = classify(raw + "\n" + (extra or ""))
    detail = raw
    if tb:
        detail += "\n\n" + tb.strip()
    if extra:
        detail += "\n\n[yt-dlp warnings]\n" + clean(extra)
    ev = {
        "id": uuid.uuid4().hex[:10],
        "time": datetime.now().strftime("%H:%M:%S"),
        "where": where,
        "code": cls["code"],
        "title": cls["title"],
        "hint": cls["hint"],
        "detail": detail[-6000:],
        "url": url or "",
        "item": item or "",
    }
    with events_lock:
        error_events.append(ev)
    log.error("[%s/%s] %s | url=%s\n%s", where, cls["code"], cls["title"], url, detail)
    ui("error_added", ev)
    return ev


def api(fn):
    """
    دکوراتور توابعی که از رابط گرافیکی صدا زده می‌شوند.
    هر استثنا ثبت می‌شود (به جای اینکه بی‌صدا گم شود).
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            record_event("python", f"{type(e).__name__}: {e}", tb=traceback.format_exc())
            return None
    return eel.expose(wrapper)


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        return
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log.critical("خطای مدیریت‌نشده:\n%s", text)
    try:
        record_event("python", f"{exc_type.__name__}: {exc}", tb=text)
    except Exception:
        pass


sys.excepthook = _excepthook
threading.excepthook = lambda a: _excepthook(a.exc_type, a.exc_value, a.exc_traceback)


# ======================================================================
#  بررسی محیط: ffmpeg ، JS runtime ، نسخه‌ها
# ======================================================================
_ffmpeg_info = None


def get_ffmpeg():
    """
    پیدا کردن ffmpeg. اگر روی سیستم نبود، نسخه‌ی همراه imageio-ffmpeg
    به پوشه‌ی bin کپی می‌شود تا yt-dlp بتواند تصویر و صدا را ادغام کند.
    """
    global _ffmpeg_info
    if _ffmpeg_info is not None:
        return _ffmpeg_info
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    info = {"available": False, "location": None, "source": "", "path": ""}

    system_path = shutil.which("ffmpeg")
    local_path = os.path.join(BIN_DIR, exe_name)
    if system_path:
        info.update(available=True, source="system", path=system_path)
    elif os.path.isfile(local_path):
        info.update(available=True, location=BIN_DIR, source="bin", path=local_path)
    else:
        try:
            import imageio_ffmpeg
            src = imageio_ffmpeg.get_ffmpeg_exe()
            os.makedirs(BIN_DIR, exist_ok=True)
            shutil.copyfile(src, local_path)
            try:
                os.chmod(local_path, 0o755)
            except Exception:
                pass
            info.update(available=True, location=BIN_DIR, source="imageio-ffmpeg", path=local_path)
        except Exception as e:
            log.warning("ffmpeg پیدا یا آماده نشد: %s", e)
    _ffmpeg_info = info
    log.info("ffmpeg: %s", info["path"] or "یافت نشد")
    return info


def find_js_runtime():
    """(نام، مسیر) اولین موتور جاوااسکریپتِ پشتیبانی‌شده؛ در صورت نبود (None, None)"""
    extra = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        os.path.expanduser(os.path.join("~", ".deno", "bin")),
    ]
    search = os.pathsep.join([os.environ.get("PATH", "")] + extra)
    for name in ("deno", "node", "bun"):  # Deno پیشنهاد رسمی yt-dlp است
        path = shutil.which(name, path=search)
        if path:
            return name, path
    return None, None


def ytdlp_age_days():
    try:
        y, m, d = (int(x) for x in YTDLP_VERSION.split(".")[:3])
        return (datetime.now() - datetime(y, m, d)).days
    except Exception:
        return None


def check_save_path(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".adm_probe_{uuid.uuid4().hex[:6]}")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True, ""
    except Exception as e:
        return False, str(e)


def get_env_checks():
    """فهرست بررسی‌های سلامت برای نمایش در تب خطاها و کادر هشدار"""
    checks = []

    ff = get_ffmpeg()
    checks.append({
        "key": "ffmpeg", "label": "ffmpeg", "ok": ff["available"],
        "value": ff["path"] or "پیدا نشد",
        "impact": "بدون ffmpeg تصویر و صدا ادغام نمی‌شوند و فقط کیفیت‌های تک‌فایل دانلود می‌شود.",
        "fix": "start.bat را دوباره اجرا کنید.",
    })

    js_name, js_path = find_js_runtime()
    checks.append({
        "key": "js", "label": "موتور جاوااسکریپت (Deno/Node)", "ok": bool(js_name),
        "value": f"{js_name}: {js_path}" if js_name else "پیدا نشد",
        "impact": "دانلود از یوتیوب ممکن است با خطای 403 یا «کیفیت موجود نیست» شکست بخورد.",
        "fix": "Deno را نصب کنید (winget install DenoLand.Deno) و برنامه را دوباره باز کنید.",
    })

    has_ejs = importlib.util.find_spec("yt_dlp_ejs") is not None
    checks.append({
        "key": "ejs", "label": "yt-dlp-ejs", "ok": has_ejs,
        "value": "نصب است" if has_ejs else "نصب نیست",
        "impact": "جزء حل چالش یوتیوب نصب نیست.",
        "fix": "start.bat را اجرا کنید (yt-dlp[default] را نصب می‌کند).",
    })

    age = ytdlp_age_days()
    old = age is not None and age > 60
    checks.append({
        "key": "ytdlp", "label": "yt-dlp", "ok": not old,
        "value": YTDLP_VERSION + (f" ({age} روز پیش)" if age is not None else ""),
        "impact": "نسخه‌ی yt-dlp قدیمی است و سایت‌ها ممکن است کار نکنند.",
        "fix": "start.bat را اجرا کنید تا بروزرسانی شود.",
    })

    ok, why = check_save_path(config_data.get("save_path", BASE_DIR))
    checks.append({
        "key": "path", "label": "مسیر ذخیره", "ok": ok,
        "value": config_data.get("save_path", "") if ok else why,
        "impact": "در این مسیر نمی‌توان فایل نوشت.",
        "fix": "مسیر ذخیره را عوض کنید.",
    })
    return checks


# ======================================================================
#  گزارش برای پشتیبان
# ======================================================================
def build_report():
    L = []
    add = L.append
    add("=" * 60)
    add(f"ADM Pro {APP_VERSION} - گزارش پشتیبانی")
    add(f"زمان: {datetime.now():%Y-%m-%d %H:%M:%S}")
    add("=" * 60)

    add("\n[محیط]")
    add(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
    add(f"Python: {sys.version.split()[0]} ({sys.executable})")
    add(f"yt-dlp: {YTDLP_VERSION}")
    try:
        add(f"eel: {importlib.metadata.version('eel')}")
    except Exception:
        pass
    for c in get_env_checks():
        add(f"{'OK ' if c['ok'] else 'BAD'} {c['label']}: {c['value']}")
    add(f"cookies_browser: {config_data.get('cookies_browser') or '(none)'}")

    with queue_lock:
        counts = Counter(t["status"] for t in download_queue)
        failed = [t for t in download_queue if t["status"] == "error"][-3:]
    add("\n[صف دانلود]")
    add(", ".join(f"{k}={v}" for k, v in counts.items()) or "(خالی)")

    with events_lock:
        events = list(error_events)[-8:]
    add(f"\n[آخرین خطاها: {len(events)}]")
    if not events:
        add("(خطایی ثبت نشده)")
    for ev in events:
        add(f"--- {ev['time']} | {ev['where']} | {ev['code']} | {ev['title']}")
        if ev["url"]:
            add(f"URL: {ev['url']}")
        add(ev["detail"][:1800])

    for t in failed:
        add(f"\n[لاگ دانلودِ ناموفق: {t['title'][:60]}]")
        add(f"URL: {t['url']}  quality={t['quality']}")
        add("\n".join(list(t.get("_log", []))[-40:]))

    add("\n[آخرین پیام‌های برنامه]")
    add("\n".join(list(memlog.buffer)[-60:]))
    return "\n".join(L)


# ======================================================================
#  لاگر yt-dlp (به‌جای AppLogger قبلی که همه‌چیز را دور می‌ریخت)
# ======================================================================
class TaskLogger:
    """همه‌ی پیام‌های yt-dlp را در فایل لاگ و در حافظه‌ی همان تسک نگه می‌دارد"""

    def __init__(self, tag, keep=120):
        self.tag = tag
        self.lines = deque(maxlen=keep)
        self.warnings = []

    def _store(self, level, msg):
        msg = clean(msg)
        self.lines.append(f"{level} {msg}")
        return msg

    def debug(self, msg):
        msg = self._store("D", msg)
        if msg.startswith("[debug]"):
            log.debug("[%s] %s", self.tag, msg)
        else:
            log.info("[%s] %s", self.tag, msg)

    def info(self, msg):
        log.info("[%s] %s", self.tag, self._store("I", msg))

    def warning(self, msg):
        msg = self._store("W", msg)
        self.warnings.append(msg)
        log.warning("[%s] %s", self.tag, msg)

    def error(self, msg):
        log.error("[%s] %s", self.tag, self._store("E", msg))


def common_ydl_opts(logger):
    """تنظیمات مشترک بین تحلیل لینک و دانلود"""
    opts = {
        "logger": logger,
        "verbose": True,       # جزئیات کامل فقط در لاگ ذخیره می‌شود
        "noprogress": True,
        "socket_timeout": 60,
        "extractor_retries": 3,
    }
    cookies = config_data.get("cookies_browser")
    if cookies:
        opts["cookiesfrombrowser"] = (cookies,)
    js_name, js_path = find_js_runtime()
    if js_name:
        opts["js_runtimes"] = {js_name: {"path": js_path}}
    return opts


# ======================================================================
#  تحلیل لینک
# ======================================================================
def extract_url(text):
    text = (text or "").strip()
    m = re.search(r"https?://[^\s\"'<>]+", text)
    if m:
        return m.group(0)
    if re.match(r"^(www\.)?[\w-]+(\.[\w-]+)+(/\S*)?$", text):
        return "https://" + text
    return None


def entry_url(entry):
    u = entry.get("url") or entry.get("webpage_url")
    if u and str(u).startswith("http"):
        return u
    ie = (entry.get("ie_key") or "").lower()
    vid = entry.get("id") or u
    if vid and ie.startswith("youtube"):
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def collect_entries(info, depth=0):
    """آیتم‌های پلی‌لیست (حتی تو در تو مثل کانال‌ها) را صاف می‌کند"""
    out = []
    for e in info.get("entries") or []:
        if not e:
            continue
        if e.get("entries") is not None and depth < 3:
            out.extend(collect_entries(e, depth + 1))
        else:
            out.append(e)
    return out


def analyze_worker(raw_text):
    tlog = TaskLogger("analyze")
    url = extract_url(raw_text)
    if not url:
        ev = record_event("analyze", f"Unsupported URL (not a link): {clean(raw_text)[:200]}", url=raw_text)
        ui("analysis_error", ev)
        return
    opts = common_ydl_opts(tlog)
    # extract_flat: پلی‌لیست‌های بزرگ در چند ثانیه خوانده می‌شوند
    opts.update({"extract_flat": "in_playlist", "socket_timeout": 30})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("yt-dlp هیچ اطلاعاتی برنگرداند")

        if info.get("entries") is not None:
            items, seen = [], set()
            for e in collect_entries(info):
                u = entry_url(e)
                if not u or u in seen:
                    log.debug("آیتم نامعتبر نادیده گرفته شد: %s", e.get("id"))
                    continue
                seen.add(u)
                items.append({
                    "id": uuid.uuid4().hex[:12],
                    "title": e.get("title") or "ویدیوی ناشناس",
                    "url": u,
                    "duration": e.get("duration"),
                })
            if not items:
                raise RuntimeError("Unsupported URL: no playable entries found in this playlist")
            ui("render_analysis", {"type": "playlist", "title": info.get("title") or "پلی‌لیست ناشناس",
                                   "items": items})
        else:
            heights = sorted(
                {f["height"] for f in info.get("formats") or []
                 if f.get("height") and f.get("vcodec") not in (None, "none")},
                reverse=True,
            )
            ui("render_analysis", {
                "type": "single",
                "title": info.get("title") or "ویدیوی ناشناس",
                "url": info.get("webpage_url") or url,
                "thumb": info.get("thumbnail") or "",
                "duration": info.get("duration"),
                "uploader": info.get("uploader") or info.get("channel") or "",
                "heights": heights,
            })
    except Exception as e:
        tb = "" if isinstance(e, yt_dlp.utils.DownloadError) else traceback.format_exc()
        ev = record_event("analyze", f"{type(e).__name__}: {e}", url=url,
                          extra="\n".join(tlog.warnings[-6:]), tb=tb)
        ui("analysis_error", ev)


@api
def analyze_url(url):
    threading.Thread(target=analyze_worker, args=(url,), daemon=True, name="analyze").start()


# ======================================================================
#  صف دانلود
# ======================================================================
download_queue = []
queue_lock = threading.RLock()
worker_running = False


class UserCancelled(Exception):
    pass


def public_task(task):
    """نسخه‌ی قابل ارسال به رابط (فیلدهای داخلی که با _ شروع می‌شوند حذف می‌شوند)"""
    return {k: v for k, v in task.items() if not k.startswith("_")}


def push_task(task, force=False):
    now = time.time()
    if not force and now - task.get("_last_push", 0) < 0.25:  # کاهش ترافیک به رابط
        return
    task["_last_push"] = now
    ui("update_task", public_task(task))


def push_queue():
    with queue_lock:
        snapshot = [public_task(t) for t in download_queue]
    ui("update_queue_ui", snapshot)


def find_task(task_id):
    with queue_lock:
        return next((t for t in download_queue if t["id"] == task_id), None)


def build_format(quality, has_ffmpeg, fallback=False):
    """رشته‌ی فرمت yt-dlp؛ بدون ffmpeg یا در حالت جایگزین فقط فایل‌های یکپارچه"""
    if quality == "best":
        return "b" if (fallback or not has_ffmpeg) else "bv*+ba/b"
    h = quality
    if fallback or not has_ffmpeg:
        return f"b[height<={h}]/b"
    return f"bv*[height<={h}]+ba/b[height<={h}]/b"


def make_progress_hook(task):
    state = {"finished": 0}

    def hook(d):
        if task.get("_cancel"):
            raise UserCancelled()
        info = d.get("info_dict") or {}
        streams = max(1, len(info.get("requested_formats") or [1]))
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                frac = done / total
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                frac = 0.0
            frac = min(max(frac, 0.0), 1.0)
            task["progress"] = round((state["finished"] + frac) / streams * 100, 1)
            task["speed"] = fmt_speed(d.get("speed"))
            task["eta"] = fmt_eta(d.get("eta"))
            task["status"] = "downloading"
            push_task(task)
        elif status == "finished":
            state["finished"] += 1
            task["progress"] = round(min(state["finished"] / streams, 1.0) * 100, 1)
            push_task(task, force=True)
    return hook


def make_pp_hook(task):
    def hook(d):
        if d.get("status") == "started":
            task.update(status="merging", speed="", eta="")
            push_task(task, force=True)
    return hook


def build_download_opts(task, tlog, fmt, ffmpeg):
    save_path = config_data.get("save_path", BASE_DIR)
    opts = common_ydl_opts(tlog)
    opts.update({
        "outtmpl": os.path.join(save_path, "%(title).100s_%(resolution)s.%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4/mkv",
        "noplaylist": True,          # خود برنامه آیتم‌های پلی‌لیست را جدا می‌کند
        "windowsfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [make_progress_hook(task)],
        "postprocessor_hooks": [make_pp_hook(task)],
        "post_hooks": [lambda filename: task.__setitem__("file", filename)],
    })
    if ffmpeg["location"]:
        opts["ffmpeg_location"] = ffmpeg["location"]
    return opts


def fail_task(task, raw, tlog=None, tb=""):
    ev = record_event(
        "download", raw, url=task["url"], item=task["title"],
        extra="\n".join(tlog.warnings[-6:]) if tlog else "", tb=tb,
    )
    task.update(status="error", speed="", eta="",
                error={"title": ev["title"], "hint": ev["hint"], "code": ev["code"], "event": ev["id"]})
    push_task(task, force=True)


def run_task(task):
    tlog = TaskLogger(task["id"][:8], keep=150)
    task["_log"] = tlog.lines
    task.update(status="downloading", progress=0.0, speed="", eta="", error=None, file="")
    task["attempts"] = task.get("attempts", 0) + 1
    push_task(task, force=True)
    log.info("شروع دانلود: %s | %s | quality=%s", task["title"], task["url"], task["quality"])

    ok, why = check_save_path(config_data.get("save_path", BASE_DIR))
    if not ok:
        fail_task(task, f"Permission denied / cannot write to save path: {why}", tlog)
        return

    ffmpeg = get_ffmpeg()
    use_fallback = False
    for attempt in (1, 2):
        fmt = build_format(task["quality"], ffmpeg["available"], fallback=use_fallback)
        log.info("[%s] format=%s (attempt %d)", tlog.tag, fmt, attempt)
        try:
            with yt_dlp.YoutubeDL(build_download_opts(task, tlog, fmt, ffmpeg)) as ydl:
                ydl.download([task["url"]])
            task.update(status="done", progress=100.0, speed="", eta="")
            push_task(task, force=True)
            log.info("دانلود کامل شد: %s", task.get("file") or task["title"])
            return
        except Exception as e:
            if task.get("_cancel") or isinstance(e, UserCancelled):
                task.update(status="cancelled", speed="", eta="")
                push_task(task, force=True)
                log.info("دانلود لغو شد: %s", task["title"])
                return
            raw = f"{type(e).__name__}: {e}"
            cls = classify(clean(e) + "\n" + "\n".join(tlog.warnings))
            # خودترمیمی: اگر مشکل از فرمت/ffmpeg بود، یک‌بار با فرمت ساده‌تر تلاش می‌کنیم
            if attempt == 1 and cls["code"] in ("format", "ffmpeg") and not use_fallback:
                log.warning("[%s] خطای %s؛ تلاش دوباره با فرمت ساده‌تر", tlog.tag, cls["code"])
                use_fallback = True
                task["progress"] = 0.0
                continue
            tb = "" if isinstance(e, yt_dlp.utils.DownloadError) else traceback.format_exc()
            fail_task(task, raw, tlog, tb)
            return


def download_worker():
    global worker_running
    try:
        while True:
            with queue_lock:
                task = next((t for t in download_queue if t["status"] == "queued"), None)
                if task is None:
                    worker_running = False   # بررسی و خروج زیر یک قفل: بدون رقابت
                    return
            try:
                run_task(task)
            except Exception as e:
                fail_task(task, f"{type(e).__name__}: {e}", tb=traceback.format_exc())
    except BaseException:
        with queue_lock:
            worker_running = False
        log.critical("نخ دانلود متوقف شد:\n%s", traceback.format_exc())
        raise


def ensure_worker():
    global worker_running
    with queue_lock:
        if worker_running:
            return
        worker_running = True
    threading.Thread(target=download_worker, daemon=True, name="download-worker").start()


@api
def add_to_queue(items, quality_str):
    m = re.search(r"(\d+)p", quality_str or "")
    quality = m.group(1) if m else "best"
    added = 0
    with queue_lock:
        existing_ids = {t["id"] for t in download_queue}
        active_urls = {t["url"] for t in download_queue if t["status"] in ("queued", "downloading", "merging")}
        for item in items or []:
            url = item.get("url")
            if not url or url in active_urls:
                continue
            task_id = item.get("id") or uuid.uuid4().hex[:12]
            if task_id in existing_ids:
                task_id = uuid.uuid4().hex[:12]
            download_queue.append({
                "id": task_id, "title": item.get("title") or url, "url": url, "quality": quality,
                "status": "queued", "progress": 0.0, "speed": "", "eta": "",
                "error": None, "file": "", "attempts": 0,
            })
            active_urls.add(url)
            added += 1
    push_queue()
    if added:
        ensure_worker()
    return added


@api
def cancel_task(task_id):
    t = find_task(task_id)
    if not t:
        return
    t["_cancel"] = True
    if t["status"] == "queued":
        t["status"] = "cancelled"
    push_task(t, force=True)


@api
def retry_task(task_id):
    t = find_task(task_id)
    if t and t["status"] in ("error", "cancelled"):
        t.update(status="queued", progress=0.0, speed="", eta="", error=None, _cancel=False)
        push_task(t, force=True)
        ensure_worker()


@api
def retry_all_failed():
    with queue_lock:
        failed = [t for t in download_queue if t["status"] == "error"]
    for t in failed:
        t.update(status="queued", progress=0.0, speed="", eta="", error=None, _cancel=False)
    push_queue()
    if failed:
        ensure_worker()
    return len(failed)


@api
def remove_task(task_id):
    with queue_lock:
        t = next((x for x in download_queue if x["id"] == task_id), None)
        if t and t["status"] not in ("downloading", "merging"):
            download_queue.remove(t)
    push_queue()


@api
def clear_finished():
    with queue_lock:
        download_queue[:] = [t for t in download_queue if t["status"] not in ("done", "cancelled")]
    push_queue()


def _open_path(path, select=False):
    if os.name == "nt":
        if select and os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path if os.path.isdir(path) else os.path.dirname(path)])
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])


@api
def show_in_folder(task_id):
    t = find_task(task_id)
    path = (t or {}).get("file") or config_data.get("save_path", BASE_DIR)
    _open_path(path, select=True)


# ======================================================================
#  تنظیمات و ابزارهای رابط
# ======================================================================
@api
def get_initial_state():
    with queue_lock:
        queue = [public_task(t) for t in download_queue]
    with events_lock:
        events = list(error_events)
    return {
        "version": APP_VERSION,
        "save_path": config_data.get("save_path", BASE_DIR),
        "cookies_browser": config_data.get("cookies_browser", ""),
        "env": get_env_checks(),
        "queue": queue,
        "events": events,
    }


@api
def refresh_env():
    global _ffmpeg_info
    _ffmpeg_info = None
    return get_env_checks()


@api
def pick_directory():
    current = config_data.get("save_path", BASE_DIR)
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        folder = filedialog.askdirectory(initialdir=current, title="انتخاب محل ذخیره پیش‌فرض")
    finally:
        root.destroy()
    if folder:
        config_data["save_path"] = os.path.normpath(folder)
        save_config()
    return config_data["save_path"]


@api
def set_cookies_browser(name):
    name = name if name in ALLOWED_BROWSERS else ""
    config_data["cookies_browser"] = name
    save_config()
    log.info("cookies_browser = %s", name or "(none)")
    return name


@api
def get_report():
    return build_report()


@api
def save_report():
    path = os.path.join(LOG_DIR, f"report_{datetime.now():%Y%m%d_%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report())
    return path


@api
def open_logs_folder():
    _open_path(LOG_DIR)


@api
def clear_errors():
    with events_lock:
        error_events.clear()


@api
def log_js_error(message, stack=""):
    """خطاهای جاوااسکریپت رابط گرافیکی هم در همین لاگ ثبت می‌شوند"""
    record_event("js", clean(message), tb=clean(stack))


# ======================================================================
#  اجرای برنامه
# ======================================================================
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    log.info("=== ADM Pro %s | yt-dlp %s | Python %s | %s ===",
             APP_VERSION, YTDLP_VERSION, sys.version.split()[0], platform.platform())
    get_ffmpeg()
    js_name, js_path = find_js_runtime()
    log.info("JS runtime: %s", f"{js_name} ({js_path})" if js_name else "پیدا نشد")

    web_dir = os.path.join(BASE_DIR, "web")
    if not os.path.isfile(os.path.join(web_dir, "index.html")):
        web_dir = BASE_DIR  # اگر index.html کنار main.py بود
    if not os.path.isfile(os.path.join(web_dir, "index.html")):
        raise FileNotFoundError("فایل index.html پیدا نشد (باید در پوشه web یا کنار main.py باشد)")
    eel.init(web_dir)

    port = free_port()
    args = dict(host="localhost", port=port, size=(900, 940), position=(300, 50),
                cmdline_args=["--disable-features=Translate"])
    for mode in ("chrome", "edge"):
        try:
            eel.start("index.html", mode=mode, **args)
            return
        except EnvironmentError as e:
            log.warning("مرورگر %s پیدا نشد: %s", mode, e)
        except (SystemExit, KeyboardInterrupt):
            return

    # اگر نه Chrome بود نه Edge: مرورگر پیش‌فرض
    log.warning("از مرورگر پیش‌فرض استفاده می‌شود")
    eel.start("index.html", mode=None, block=False, host="localhost", port=port)
    webbrowser.open(f"http://localhost:{port}/index.html")
    while True:
        eel.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        pass
    except BaseException:
        text = traceback.format_exc()
        log.critical("برنامه با خطا بسته شد:\n%s", text)
        show_fatal("ADM Pro", "برنامه با خطا بسته شد.\n\nجزئیات در فایل logs\\app.log ذخیره شد.\n\n" + text[-600:])
        sys.exit(1)
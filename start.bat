@echo off
chcp 65001 >nul
title ADM Pro Downloader
cd /d "%~dp0"
if not exist logs mkdir logs

REM ============================================
REM   ADM Pro - اجرای خودکار با بروزرسانی
REM   این فایل را دابل‌کلیک کنید، کافی است.
REM   خروجی نصب و بروزرسانی در logs\setup.log ذخیره می‌شود.
REM ============================================

REM --- بررسی وجود پایتون ---
where python >nul 2>nul
if %errorlevel% neq 0 goto :nopython

REM --- نصب/بروزرسانی کتابخانه‌ها ---
REM تلاش اول: نصب کامل. اگر یکی از بسته‌های اختیاری ^(مثل brotli^) روی این نسخه‌ی پایتون
REM نصب نشد، پیپ همه را رها می‌کند؛ پس در تلاش دوم بسته‌های لازم را جدا نصب می‌کنیم.
echo  در حال بررسی و بروزرسانی کتابخانه‌ها...
python -m pip install --upgrade --disable-pip-version-check --timeout 15 --retries 2 "yt-dlp[default]" eel imageio-ffmpeg >> logs\setup.log 2>&1
if not errorlevel 1 goto :pipok
echo  نصب کامل نشد؛ نصب بسته‌های ضروری به‌صورت جداگانه...
python -m pip install --upgrade --disable-pip-version-check --timeout 15 --retries 2 yt-dlp yt-dlp-ejs eel imageio-ffmpeg >> logs\setup.log 2>&1
if errorlevel 1 (
    echo  هشدار: بروزرسانی انجام نشد ^(شاید اینترنت قطع است^). با نسخه فعلی ادامه می‌دهیم.
    echo  جزئیات در logs\setup.log است.
)
:pipok

REM --- موتور جاوااسکریپت برای یوتیوب ^(Deno یا Node^) ---
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.deno\bin"
where deno >nul 2>nul && goto :jsready
where node >nul 2>nul && goto :jsready
where winget >nul 2>nul || goto :jsmissing
echo  در حال نصب Deno برای پشتیبانی از یوتیوب...
winget install --id=DenoLand.Deno -e --source winget --silent --accept-source-agreements --accept-package-agreements >> logs\setup.log 2>&1
:jsmissing
where deno >nul 2>nul || echo  هشدار: Deno نصب نشد. دانلود از یوتیوب ممکن است خطا بدهد.
:jsready

REM --- اجرای برنامه اصلی ---
python main.py
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo  برنامه با خطا بسته شد ^(کد %RC%^).
    echo  جزئیات در logs\app.log ذخیره شده است.
    if not defined ADM_SILENT pause
)
exit /b %RC%

:nopython
echo.
echo  [خطا] پایتون روی سیستم شما پیدا نشد!
echo  لطفاً از سایت python.org آخرین نسخه را نصب کنید
echo  و حتماً تیک "Add Python to PATH" را بزنید.
echo.
if not defined ADM_SILENT pause
exit /b 1
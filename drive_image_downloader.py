# -*- coding: utf-8 -*-
"""
谷歌云盘图片批量下载器（支持 Facebook Reels）
功能：
  1. 粘贴多个 Google Drive 分享链接（每行一个），批量下载到本地
     （图片和视频都支持，视频同样按链接下载）
  2. 支持 Facebook Reels 链接（https://www.facebook.com/reel/xxx），
     同样按顺序编号下载为 mp4（需要安装 yt-dlp：pip3 install yt-dlp）
  3. 手动设置起始序号，下载时按顺序自动重命名：
     例如起始序号=1、2位补零  ->  01.jpg, 02.jpg, 03.jpg ...（视频则为 01.mp4, 02.mp4 ...）
     例如起始序号=23         ->  23.jpg, 24.jpg, 25.jpg ...
  4. 文件扩展名（.jpg/.png/.mp4/.mov 等）自动从原文件获取，保持不变
  5. 序号位数可选：不补零 / 2位（01） / 3位（001）

运行环境：只需要 Python 3（无需安装任何第三方库），Windows / Mac / Linux 通用。
          下载 Facebook Reels 需要额外安装 yt-dlp（见使用说明）。
使用方法：双击运行本文件，或在命令行执行  python drive_image_downloader.py
"""

import os
import re
import sys
import threading
import urllib.request
import urllib.parse
import urllib.error
from email.message import Message

# 打包版（PyInstaller）在 Windows / Mac 上可能找不到系统根证书，
# 导致 HTTPS 证书校验失败；如果打包时带了 certifi，就用它的证书包。
# 直接运行源码时一般不需要（没装 certifi 也完全不影响）。
try:
    import certifi as _certifi

    os.environ.setdefault("SSL_CERT_FILE", _certifi.where())
except ImportError:
    _certifi = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


class _StopRequested(Exception):
    """用户点了停止按钮时用于中断下载的内部异常。"""
    pass

CONTENT_TYPE_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/svg+xml": ".svg",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "video/x-m4v": ".m4v",
}


def extract_file_id(text):
    """从一行文本中提取 Google Drive 文件 ID。支持 /file/d/<id>/ 形式和纯 ID。"""
    text = text.strip()
    if not text:
        return None
    m = re.search(r"/d/([A-Za-z0-9_-]{10,})", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text
    return None


FB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:facebook\.com|fb\.watch)/\S+",
    re.IGNORECASE)


def is_facebook_url(text):
    """判断是否为 Facebook 链接（reels、watch、小组帖子、分享链接等）。
    具体是不是视频由 yt-dlp 下载时判断，不是视频会给出明确报错。"""
    return bool(FB_URL_RE.search(text.strip()))


def check_yt_dlp():
    """检查 yt-dlp 是否可用（下载 Facebook 视频需要）。"""
    try:
        import yt_dlp  # noqa
        return True
    except ImportError:
        return False


def download_facebook_video(url, dest_base, progress_cb=None, chunk_unused=None, stop_check=None):
    """
    用 yt-dlp 下载 Facebook 视频/Reels。
    dest_base: 不带扩展名的目标路径；下载后自动补上真实扩展名。
    stop_check() 返回 True 时中断下载并删除未下完的文件。
    返回 (成功 True/False, 成功时为最终文件路径 / 失败时为错误信息)。
    """
    if not check_yt_dlp():
        return False, ("缺少 yt-dlp，无法下载 Facebook 视频。\n"
                       "请先安装：pip3 install yt-dlp（Mac / Linux）\n"
                       "或：pip install yt-dlp（Windows），然后重新打开软件。")
    import yt_dlp
    import glob

    tmp_tmpl = dest_base + ".fbdl.%(ext)s"

    def hook(d):
        if stop_check and stop_check():
            raise _StopRequested()
        if not progress_cb:
            return
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            progress_cb(d.get("downloaded_bytes") or 0, total)
        elif st == "finished":
            total = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            progress_cb(total, total)

    ydl_opts = {
        "format": "b",            # 最佳单个文件（reels 通常是单个 mp4，无需 ffmpeg 合并）
        "outtmpl": tmp_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,       # 进度由 progress_hooks 回调到界面，不在终端刷屏
        "noplaylist": True,
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    except _StopRequested:
        for p in glob.glob(dest_base + ".fbdl.*"):
            try:
                os.remove(p)
            except OSError:
                pass
        return False, "已停止"
    except Exception as e:
        msg = str(e)
        if "login" in msg.lower() or "cookies" in msg.lower():
            return False, "该视频需要登录 Facebook 才能下载"
        return False, "Facebook 下载失败: %s" % msg[:160]

    cands = glob.glob(dest_base + ".fbdl.*")
    cands = [c for c in cands if not c.endswith(".part")]
    if not cands:
        return False, "下载完成但找不到文件"
    src = cands[0]
    _, ext = os.path.splitext(src)
    final = dest_base + (ext or ".mp4")
    try:
        os.replace(src, final)
    except Exception as e:
        return False, "重命名失败: %s" % e
    return True, final


def _get_ext_from_response(resp, file_id):
    """从响应头推断文件扩展名。"""
    cd = resp.headers.get("Content-Disposition", "")
    if cd:
        msg = Message()
        msg["Content-Disposition"] = cd
        fname = msg.get_filename()
        if fname:
            _, ext = os.path.splitext(fname)
            if ext:
                return ext.lower()
    ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
    if ctype in CONTENT_TYPE_TO_EXT:
        return CONTENT_TYPE_TO_EXT[ctype]
    return ".jpg"  # 默认


def download_file(file_id, dest_path, progress_cb=None, chunk=65536, stop_check=None):
    """
    下载单个 Drive 文件到 dest_path。
    progress_cb(downloaded_bytes, total_bytes) 会被反复调用（total 可能为 None）。
    stop_check() 返回 True 时立即中断并删除未下完的文件。
    返回 (成功 True/False, 信息字符串)。
    """
    qid = urllib.parse.quote(file_id)
    # 新版直连地址（带 confirm=t，大文件也不弹确认页）；旧版地址作为备用
    urls = [
        "https://drive.usercontent.google.com/download?id=%s&export=download&confirm=t" % qid,
        "https://drive.google.com/uc?export=download&id=%s&confirm=t" % qid,
    ]

    def open_url(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=60)

    resp = None
    last_err = None
    for url in urls:
        try:
            resp = open_url(url)
            ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
            if ctype != "text/html":
                break  # 拿到文件流，直接用
            # 仍是 HTML（旧版确认页），走下面的确认页逻辑
            break
        except Exception as e:
            last_err = e
            resp = None
    if resp is None:
        return False, "网络错误: %s" % last_err

    try:
        ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        # 大文件会返回一个确认页面（text/html），需要带 confirm 参数再请求一次
        if ctype == "text/html":
            html = resp.read(2 * 1024 * 1024).decode("utf-8", "ignore")
            m = re.search(r"confirm=([0-9A-Za-z_=-]+)", html)
            if not m:
                low = html.lower()
                if ("quota" in low or "too many" in low or "try again" in low
                        or "tente novamente" in low or "很抱歉" in html
                        or "temporarily unavailable" in low):
                    return False, ("谷歌暂时限制了下载（下载太频繁或配额用完），"
                                   "请过几小时再试，不要连续重复下载")
                return False, ("谷歌返回了确认页面但无法继续，可能是大文件限制或临时限制，"
                               "请稍后再试")
            confirm = m.group(1)
            url2 = ("https://drive.google.com/uc?export=download&id=" + qid
                    + "&confirm=" + urllib.parse.quote(confirm))
            try:
                resp.close()
                resp = open_url(url2)
            except Exception as e:
                return False, "网络错误: %s" % e
            ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
            if ctype == "text/html":
                return False, "仍被要求确认，可能是大文件或权限问题"

        total = resp.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None
        downloaded = 0
        tmp_path = dest_path + ".downloading"
        was_stopped = False
        try:
            with open(tmp_path, "wb") as f:
                while True:
                    if stop_check and stop_check():
                        was_stopped = True
                        break
                    data = resp.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    downloaded += len(data)
                    if progress_cb:
                        progress_cb(downloaded, total)
        finally:
            resp.close()
        if was_stopped:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False, "已停止"
        os.replace(tmp_path, dest_path)
        return True, "OK"
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False, "下载失败: %s" % e


def download_batch(links, start_number, out_dir, prefix="", zero_pad=0,
                   status_cb=None, file_progress_cb=None, overall_progress_cb=None,
                   stop_flag=None):
    """
    批量下载（支持 Google Drive 链接和 Facebook Reels 链接混排）。
    返回 (成功数, [(序号, 原始链接, 结果信息), ...])。
    """
    results = []
    items = []  # (link, kind, file_id)
    for link in links:
        link = link.strip()
        if not link:
            continue
        # 注意：重复的链接不跳过，每一行都会下载并占用一个序号
        if is_facebook_url(link):
            items.append((link, "facebook", None))
            continue
        fid = extract_file_id(link)
        if fid:
            items.append((link, "drive", fid))
        else:
            results.append((None, link, "无法识别的链接"))

    total = len(items)
    ok_count = 0
    n = start_number
    for i, (link, kind, fid) in enumerate(items):
        if stop_flag and stop_flag():
            results.append((None, link, "已停止"))
            break
        if status_cb:
            status_cb("正在下载第 %d/%d 个 ..." % (i + 1, total))

        num_str = str(n)
        if zero_pad and zero_pad > 0:
            num_str = num_str.zfill(zero_pad)
        base_name = ("%s_%s" % (prefix, num_str)) if prefix else num_str

        def _cb(d, t, _i=i, _t=total):
            if file_progress_cb:
                file_progress_cb(_i, _t, d, t)

        if kind == "drive":
            # 先请求一次拿到扩展名（复用 download_file 内部逻辑则需二次请求；
            # 这里简单做法：先 HEAD 式探测扩展名）
            ext = probe_ext(fid)
            dest = os.path.join(out_dir, base_name + ext)
            dest = _avoid_overwrite(dest)
            success, info = download_file(fid, dest, progress_cb=_cb, stop_check=stop_flag)
        else:  # facebook
            tmp_base = os.path.join(out_dir, ".tmp_fb_%d" % i)
            success, info = download_facebook_video(link, tmp_base, progress_cb=_cb,
                                                    stop_check=stop_flag)

        if info == "已停止":
            results.append((n, link, "已停止"))
            break

        if kind == "drive":
            if success:
                ok_count += 1
                results.append((n, link, os.path.basename(dest)))
            else:
                results.append((n, link, "失败: " + info))
        else:  # facebook
            if success:
                _, ext = os.path.splitext(info)
                dest = os.path.join(out_dir, base_name + (ext or ".mp4"))
                dest = _avoid_overwrite(dest)
                try:
                    os.replace(info, dest)
                    ok_count += 1
                    results.append((n, link, os.path.basename(dest)))
                except Exception as e:
                    results.append((n, link, "失败: 重命名失败 %s" % e))
            else:
                results.append((n, link, "失败: " + info))
        if overall_progress_cb:
            overall_progress_cb(i + 1, total)
        n += 1
    return ok_count, results


def _avoid_overwrite(dest):
    """如果目标文件已存在，自动改名，不覆盖。"""
    k = 1
    stem, suffix = os.path.splitext(dest)
    while os.path.exists(dest):
        dest = "%s(%d)%s" % (stem, k, suffix)
        k += 1
    return dest


def probe_ext(file_id):
    """探测文件的扩展名（只读响应头，不下载正文）。"""
    qid = urllib.parse.quote(file_id)
    urls = [
        "https://drive.usercontent.google.com/download?id=%s&export=download&confirm=t" % qid,
        "https://drive.google.com/uc?export=download&id=%s" % qid,
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=30)
            try:
                ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
                if ctype == "text/html":
                    continue  # 确认页，换备用地址
                return _get_ext_from_response(resp, file_id)
            finally:
                resp.close()
        except Exception:
            continue
    return ".jpg"


# ---------------------------------------------------------------- GUI
def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    root = tk.Tk()
    root.title("谷歌云盘图片批量下载器")
    root.geometry("640x560")
    root.minsize(560, 480)

    # ---- 链接输入
    ttk.Label(root, text="1. 粘贴链接（每行一个，按粘贴顺序下载）：\n"
                         "   • Google Drive 分享链接（图片/视频）\n"
                         "   • Facebook Reels 链接（需安装 yt-dlp，见使用说明）").pack(anchor="w", padx=12, pady=(12, 4))
    txt = scrolledtext.ScrolledText(root, height=9, wrap="none", font=("Consolas", 10))
    txt.pack(fill="both", expand=False, padx=12)

    # ---- 参数区
    frm = ttk.Frame(root)
    frm.pack(fill="x", padx=12, pady=10)

    ttk.Label(frm, text="2. 起始序号：").grid(row=0, column=0, sticky="w")
    start_var = tk.StringVar(value="1")
    ttk.Entry(frm, textvariable=start_var, width=8).grid(row=0, column=1, sticky="w", padx=(0, 16))

    ttk.Label(frm, text="文件名前缀（可选）：").grid(row=0, column=2, sticky="w")
    prefix_var = tk.StringVar(value="")
    ttk.Entry(frm, textvariable=prefix_var, width=12).grid(row=0, column=3, sticky="w", padx=(0, 16))

    ttk.Label(frm, text="序号位数：").grid(row=0, column=4, sticky="w")
    pad_var = tk.StringVar(value="2位（01）")
    pad_box = ttk.Combobox(frm, textvariable=pad_var, width=10, state="readonly",
                           values=["不补零", "2位（01）", "3位（001）"])
    pad_box.grid(row=0, column=5, sticky="w")

    ttk.Label(frm, text="3. 保存文件夹：").grid(row=1, column=0, sticky="w", pady=(10, 0))
    out_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads", "drive_images"))
    ttk.Entry(frm, textvariable=out_var, width=52).grid(row=1, column=1, columnspan=3, sticky="we", pady=(10, 0))
    ttk.Button(frm, text="选择…", command=lambda: _choose_dir(out_var)).grid(row=1, column=4, sticky="w", pady=(10, 0))
    frm.columnconfigure(1, weight=1)

    # ---- 进度
    status_var = tk.StringVar(value="就绪")
    ttk.Label(root, textvariable=status_var).pack(anchor="w", padx=12)
    bar = ttk.Progressbar(root, mode="determinate", maximum=100)
    bar.pack(fill="x", padx=12, pady=4)

    # ---- 日志
    log = scrolledtext.ScrolledText(root, height=8, state="disabled", font=("Consolas", 9))
    log.pack(fill="both", expand=True, padx=12, pady=(4, 8))

    def log_msg(s):
        log.configure(state="normal")
        log.insert("end", s + "\n")
        log.see("end")
        log.configure(state="disabled")

    # ---- 按钮
    btn_frm = ttk.Frame(root)
    btn_frm.pack(fill="x", padx=12, pady=(0, 12))
    dl_btn = ttk.Button(btn_frm, text="开始下载")
    dl_btn.pack(side="left")
    stop_btn = ttk.Button(btn_frm, text="停止", state="disabled")
    stop_btn.pack(side="left", padx=8)
    open_btn = ttk.Button(btn_frm, text="打开保存文件夹",
                          command=lambda: _open_folder(out_var.get()))
    open_btn.pack(side="right")

    stop_requested = {"v": False}

    def _choose_dir(var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def run():
        raw = txt.get("1.0", "end").strip().splitlines()
        links = [l for l in (x.strip() for x in raw) if l]
        if not links:
            messagebox.showwarning("提示", "请先粘贴至少一个链接。")
            return
        try:
            start = int(start_var.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "起始序号必须是整数。")
            return
        # 有 Facebook 链接时，提前检查 yt-dlp
        if any(is_facebook_url(l) for l in links) and not check_yt_dlp():
            messagebox.showwarning(
                "需要安装 yt-dlp",
                "检测到 Facebook 链接，但本机没有安装 yt-dlp，无法下载。\n\n"
                "请先安装（只需一次）：\n"
                "Mac / Linux（终端执行）：pip3 install yt-dlp\n"
                "Windows（cmd 执行）：pip install yt-dlp\n\n"
                "安装后重新打开本软件再下载。")
            return
        out_dir = out_var.get().strip() or os.path.join(os.path.expanduser("~"), "Downloads")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", "无法创建保存文件夹：%s" % e)
            return
        prefix = prefix_var.get().strip()
        pad_choice = pad_var.get()
        zero_pad = {"2位（01）": 2, "3位（001）": 3}.get(pad_choice, 0)

        dl_btn.configure(state="disabled")
        stop_btn.configure(state="normal")
        stop_requested["v"] = False
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

        def status_cb(s):
            root.after(0, lambda: status_var.set(s))

        def file_cb(i, total, d, t):
            def _u():
                if t:
                    bar["value"] = (i + d / t) / total * 100
                    status_var.set("正在下载第 %d/%d 个：%s / %s" % (i + 1, total, _fmt(d), _fmt(t)))
                else:
                    status_var.set("正在下载第 %d/%d 个：%s" % (i + 1, total, _fmt(d)))
            root.after(0, _u)

        def overall_cb(i, total):
            root.after(0, lambda: bar.configure(value=i / total * 100))

        def worker():
            ok, results = download_batch(
                links, start, out_dir, prefix=prefix, zero_pad=zero_pad,
                status_cb=status_cb, file_progress_cb=file_cb,
                overall_progress_cb=overall_cb,
                stop_flag=lambda: stop_requested["v"])
            def done():
                for num, link, info in results:
                    if num is None:
                        log_msg("[跳过] %s -> %s" % (link, info))
                    elif info == "已停止":
                        log_msg("[停止] 序号 %s -> 已停止" % num)
                    elif info.startswith("失败"):
                        log_msg("[失败] 序号 %s -> %s" % (num, info))
                    else:
                        log_msg("[成功] 序号 %s -> %s" % (num, info))
                log_msg("完成：成功 %d 个。" % ok)
                status_var.set("完成：成功 %d 个，保存到 %s" % (ok, out_dir))
                bar["value"] = 100
                dl_btn.configure(state="normal")
                stop_btn.configure(state="disabled")
            root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _fmt(n):
        if n >= 1048576:
            return "%.1f MB" % (n / 1048576)
        if n >= 1024:
            return "%.0f KB" % (n / 1024)
        return "%d B" % n

    dl_btn.configure(command=run)
    stop_btn.configure(command=lambda: stop_requested.update(v=True))

    root.mainloop()


def _open_folder(path):
    import subprocess
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


if __name__ == "__main__":
    main()

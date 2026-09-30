# 云盘图片下载器

批量下载 Google Drive 图片/视频、Facebook 公开 Reels 的小工具。

## 下载安装包

直接去 [最新版发布页](https://github.com/dage67697-hub/drive-media-downloader/releases/tag/latest) 下载：

- Windows：`云盘图片下载器.exe`（双击运行）
- Mac：`云盘图片下载器.dmg`（打开后把应用拖到「应用程序」文件夹）

> 未签名说明：Windows 首次运行若出现 SmartScreen 提示，点「更多信息」→「仍要运行」；
> Mac 首次打开若被拦截，右键点击应用 →「打开」即可。

## 用法

1. 把 Google Drive 分享链接（`/file/d/<id>/view` 格式）或 Facebook 公开 Reels 链接，一行一条粘贴进去
2. 设置起始序号（默认从 1 开始，按粘贴顺序编号，如 01.jpg、02.mp4……）
3. 点「开始下载」

详细说明见 `使用说明.txt`。Facebook 视频下载需要本机安装 yt-dlp（`pip install yt-dlp`）。

## 自动打包

每次推送到 `main` 分支，GitHub Actions 会自动在 Windows 和 macOS 上打包，并更新到最新版发布页。

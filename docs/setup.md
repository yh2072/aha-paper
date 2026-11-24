# Setup · 安装与部署

[← README](../README.md) · [← 中文说明](../README.zh.md)

Everything past the quick start: containers, a desktop window, a signed
installer, and running it on a server.

---

## English

## With Docker

```sh
cp .env.example .env          # must exist: it is bind-mounted, not baked in
docker compose up --build
```

Three paths live on the host, not in the image: `data/` (papers and everything
generated from them), `.runtime/` (the provider credential store) and `.env`.
Saving a model or a voice in the interface writes back to `.env`, which is why it
is mounted rather than passed as environment variables.

## As a desktop window

```bash
npm install && npm run desktop
```

Starts the server on a free port and opens it in a window — no terminal, no
URL to remember. It uses Electron's own Node for the provider CLI, so Node is
not a separate prerequisite.

This is the shell only: it runs against the Python environment on your machine.
Shipping it as a double-clickable app means bundling Python, the dependencies
and ffmpeg (~430 MB per platform) and signing the result. `app/bin.py` is the
part that makes that possible — every external program is resolved through it,
so a build can point `AHA_BIN_DIR` at the copies inside its own bundle.

## Building an installer

```bash
npm run icon
npm run bundle:runtime
npm run dist:mac
```

`bundle:runtime` fetches a relocatable CPython, installs `requirements.txt` into
it, and fetches static ffmpeg and ffprobe into `runtime/`. The machine's own
copies cannot be used: a venv's interpreter is a symlink to a Python elsewhere
on disk, and Homebrew's ffmpeg links against dylibs under `/opt/homebrew`, so
either one produces a build that runs only where it was built.

The result is roughly 470 MB per platform — Electron ~150 MB, the wheels
~162 MB, ffmpeg and ffprobe ~92 MB, fonts and the figure model ~38 MB.

**Signing is yours to do.** Unsigned, macOS tells whoever downloads it that the
app "cannot be opened because the developer cannot be verified", and the only
way past that is right-click → Open. To avoid it you need an Apple Developer
account and a Developer ID Application certificate; then

```bash
CSC_LINK=... CSC_KEY_PASSWORD=... APPLE_ID=... APPLE_APP_SPECIFIC_PASSWORD=... APPLE_TEAM_ID=... npm run dist:mac
```

The hardened runtime is already configured, with the entitlements the bundled
CPython and the wheels' native extensions need (`build/entitlements.mac.plist`).

**ffmpeg's licence travels with it.** The static builds are redistributed
inside the app, so their licence ships beside them in `Resources/bin`. Check
which terms the build you fetch is under before handing the app to anyone.

## Hosting it

A run takes about 5 minutes, writes roughly 86 MB per paper, and keeps working
on background threads after the HTTP response. That rules out serverless. It
suits anything that runs the container and keeps it up — Railway, Fly.io, Render,
or a small VPS with `docker compose`. The image reads `$PORT` where the platform
sets one.

Three constraints to carry over:

- **Mount a volume at `/app/data`.** Without one, every paper and everything
  generated from it disappears on each deploy.
- **One replica.** In-flight jobs live in a thread pool and a dict inside the
  process; a second instance would not see them.
- **Set `AHA_ACCESS_PASSWORD`.** Unset, there is no gate: anyone with the URL
  can upload papers, open the settings and spend your API credit.

Set, it puts one shared password in front of everything — studio, player, API
and the `data/` directory — and remembers it in a signed, `HttpOnly` cookie for
30 days. It is a door, not a user system: one password, no accounts, no roles.
Changing it signs everyone out. Guesses are rate-limited per client and in total.

Point the platform's health check at **`/api/ping`**, which stays open and
answers `{"ok": true}`. `/api/health` is behind the password, and a probe that
gets a 401 will have the platform restart a container that is serving fine.

---

## 中文

## 用 Docker

```sh
cp .env.example .env          # 必须先建：它是挂进去的，不打进镜像
docker compose up --build
```

三个路径留在宿主机而不进镜像：`data/`（论文与全部产出）、`.runtime/`（供应商凭据）
和 `.env`。在界面里改模型或音色会写回 `.env`，所以用挂载而不是环境变量传入。

## 当成桌面应用跑

```bash
npm install && npm run desktop
```

自动挑一个空闲端口起服务，并开一个窗口指过去——不用开终端，也不用记网址。
供应商 CLI 用的是 Electron 自带的 Node，所以不需要另外装 Node。

目前只有外壳：它跑的是你机器上的 Python 环境。要做成双击就能用的安装包，
得把 Python、依赖和 ffmpeg 一起打进去（每个平台约 430 MB）并签名。
`app/bin.py` 就是为此准备的——所有外部程序都从那里解析，
打包后把 `AHA_BIN_DIR` 指向自带的那份即可。

## 打包成安装包

```bash
npm run icon
npm run bundle:runtime
npm run dist:mac
```

`bundle:runtime` 会下载一份可重定位的 CPython，把 `requirements.txt` 装进去，
再下载静态的 ffmpeg 和 ffprobe 到 `runtime/`。不能直接用本机那份：venv 里的
解释器是指向磁盘别处的符号链接，而 Homebrew 的 ffmpeg 链接到 `/opt/homebrew`
下面的 dylib——两者都会打出一个只在打包这台机器上能跑的包。

成品每个平台约 470 MB：Electron ~150 MB，wheels ~162 MB，
ffmpeg 与 ffprobe ~92 MB，字体和主图检测模型 ~38 MB。

**签名要你自己来。**不签名的话，别人下载后 macOS 会说"无法打开，因为无法验证
开发者"，只能右键→打开绕过。要免掉这一步需要 Apple 开发者账号和一张
Developer ID Application 证书，然后：

```bash
CSC_LINK=... CSC_KEY_PASSWORD=... APPLE_ID=... APPLE_APP_SPECIFIC_PASSWORD=... APPLE_TEAM_ID=... npm run dist:mac
```

加固运行时（hardened runtime）已经配好，包含自带 CPython 和各 wheel 里原生扩展
所需的 entitlements，见 `build/entitlements.mac.plist`。

**ffmpeg 的许可证要跟着走。**静态构建是随应用一起分发的，所以它的许可证文件
会放在 `Resources/bin` 旁边。把应用交给别人之前，先确认你下载的那份是什么条款。

## 部署到哪里

一次任务约 5 分钟，每篇论文写出约 86 MB，而且 HTTP 响应返回后还在后台线程里继续跑。
这几条把 serverless 排除了。能跑容器并让它常驻的都合适——Railway、Fly.io、Render，
或者一台小 VPS 上 `docker compose`。平台注入 `$PORT` 时镜像会读它。

有三条约束要一起带过去：

- **给 `/app/data` 挂卷。**不挂的话，每次部署论文和全部产出都会消失。
- **只能单副本。**在跑的任务存在进程内的线程池和字典里，第二个实例看不到它们。
- **设 `AHA_ACCESS_PASSWORD`。**不设就是完全没有门：任何拿到网址的人都能上传论文、
  打开设置页、花掉你的 API 余额。

设了之后，工作室、播放页、API 和 `data/` 目录全部在一个共享口令后面，用签名的
`HttpOnly` cookie 记住 30 天。它只是一道门，不是账号系统：一个口令，没有账号也没有角色。
改口令等于把所有人登出。猜口令按客户端和全局两重限速。

平台的健康检查请指向 **`/api/ping`**——它不设门，只回 `{"ok": true}`。
`/api/health` 在口令后面，探针拿到 401 会让平台把一个服务正常的容器反复重启。

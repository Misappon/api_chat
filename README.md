# API Chat

一个本地优先的 Win64 多模型聊天客户端。用 PySide6 构建界面，对话、API 配置、附件和用量统计保存在本地 MySQL；支持 OpenAI 兼容接口、Anthropic 和 Google Gemini，也可以把对话共享给局域网内的手机浏览器继续使用。

![对话界面](docs/screenshot-chat.png)

![综合控制台](docs/screenshot-dashboard.png)

> 截图使用演示数据；`scripts/seed_demo.py` 可以生成同款本地演示数据库，不会写入 `api_chat`。

## 功能

- **多 API 管理**：每个 API 可设置别名、Base URL、模型、上下文窗口、最大输出、温度和系统提示词；对话内可随时切换 API。
- **MySQL 对话存储**：默认数据库 `api_chat`，首次运行自动建库建表；对话列表支持新建、搜索、重命名、删除和清空。
- **单条消息修改**：用户消息可「保存并重新提交」，自动删除该消息之后的旧回复并重新请求模型；助手消息可编辑保存到历史。
- **剩余上下文百分比**：对话列表和对话头部都显示剩余上下文，按消息 token 估算与模型窗口计算；低于阈值会变色提醒。
- **模型自动标题**：第一轮回复后由模型生成简短标题，可在标题栏直接改名，也可从菜单重新生成。
- **综合控制台**：总 Tokens、输入/输出 Tokens、请求数、对话用量排行、各对话明细、按 API 汇总；支持一键切换数据库。
- **本地用量联动**：消息被编辑、截断、删除或对话被清空/删除时，关联的用量事件会一起更新。
- **附件、图片与 PDF**：支持图片（PNG/JPG/WebP/GIF/BMP）、PDF 和文本/代码文件，可拖入、粘贴或选择文件；图片会随消息进入多模态请求，PDF 会提取文本作为上下文，支持预览和附件保存。
- **网页对话导入**：从「新建对话」右侧的「…」进入，可读取公开的 ChatGPT / Claude / Gemini / DeepSeek 分享链接、另存的 HTML，或粘贴带 User/Assistant 标记的文本。
- **文本导出**：任意本地对话可导出为 UTF-8 文本，包含标题、API、模型、时间和附件清单。
- **局域网共享**：启动带访问码的本地 HTTP 服务，手机连接同一 Wi-Fi 后即可查看对话、发送消息和查看附件；服务只共享当前 MySQL 数据库。
- **输入框与全局字号**：输入框随文本行数自动增高；综合控制台右上角可调整全局字号，也支持 `Ctrl+Shift++` / `Ctrl+Shift+-`，字号会保存到本地配置。
- **实时 Markdown 输出**：流式生成过程中即按标题、粗体、列表、代码块和表格渲染，不再等生成结束才格式化。
- **多级推理**：输入框左侧「思考」等级选择；按模型类别提供关/低/中/高（DeepSeek 为关/高），并折叠显示思考过程。
- **在线搜索与搜索源**：输入框左侧「联网」开关；综合控制台可增删 Bing / DuckDuckGo / SearXNG / Tavily 搜索源、逐个启用和调整优先级。思考与联网同时开启时执行最多 3 轮的“思考 → 搜索 → 评估”循环。
- **Windows 原生体验**：深色界面、流式输出、停止生成、错误重试、快捷键、HiDPI 支持和自定义应用图标。

## 快速开始

### 环境要求

- Windows 10/11 x64
- MySQL 8.x（默认 `127.0.0.1:3306`，用户 `root`，空密码）
- 已安装 Miniconda / Anaconda，且 `conda` 在 PATH 中

### 方式一：源码运行

1. 确认 MySQL 服务已启动：

   ```powershell
   Get-Service MySQL
   ```

2. 如果本机还没有 `apichat` conda 环境，双击 `setup_env.bat`，或手动执行：

   ```powershell
   conda create -n apichat python=3.11 -y
   conda activate apichat
   python -m pip install -r requirements.txt
   ```

3. 双击 `run.bat` 启动。调试时使用 `run_debug.bat`，可以看控制台日志。

首次启动会自动创建 `api_chat` 数据库和以下表：

```
api_providers  conversations  messages  attachments  usage_events  app_meta
```

如果 MySQL 连接失败，程序会弹出数据库设置窗口，可修改主机、端口、用户名、密码和数据库名。

### 方式二：打包版

```powershell
build_exe.bat
```

产物在 `dist\APIChat\APIChat.exe`。整个 `dist\APIChat` 文件夹需要一起复制，不能只拿走 exe。打包版同样需要本机 MySQL 服务。

## 配置 API

打开左侧「API 管理」→「添加 API」，至少填写：

| 字段 | 说明 |
|---|---|
| 别名 | 对话列表和顶部选择器中显示的名称，不能重复 |
| 提供商类型 | OpenAI 兼容 / Anthropic / Google Gemini |
| Base URL | 接口根地址，通常填到 `/v1` |
| 模型名称 | 服务商实际支持的模型 ID |
| API Key | 本地服务可留空；保存在本地 MySQL 中 |
| 上下文窗口 | 用于计算剩余上下文百分比 |
| 单次最大输出 | 每次请求的 `max_tokens` |
| 系统提示词 | 可选，会对该 API 的所有对话生效 |

常用配置示例：

| 服务 | 类型 | Base URL | 模型示例 |
|---|---|---|---|
| OpenAI | OpenAI 兼容 | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | OpenAI 兼容 | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenRouter | OpenAI 兼容 | `https://openrouter.ai/api/v1` | 以 OpenRouter 模型页为准 |
| Ollama | OpenAI 兼容 | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` 等本地模型 |
| Anthropic | Anthropic | `https://api.anthropic.com/v1` | `claude-sonnet-4-20250514` |
| Google Gemini | Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | `gemini-2.5-pro` |

![API 管理](docs/screenshot-api.png)

编辑窗口里的「测试连接」会发送一个极短的请求验证地址、密钥和模型。模型 ID 会随服务商更新，请以实际账号可用列表为准。

## 使用

### 对话与 API

- 点击「新建对话」创建会话；每个对话独立绑定一个 API，顶部下拉框可随时切换。
- 对话列表显示：标题、API 别名、消息数、累计 Tokens、剩余上下文百分比。
- 右键对话卡片可重命名、自动生成标题、清空消息或删除。
- 搜索框按标题过滤对话。

### 上下文百分比

- 百分比 = `1 - 当前消息估算 tokens / 模型上下文窗口`。
- 对话头部的提示会显示已用/总窗口；顶部「自动标题」表示标题由模型生成。
- 估算按中英文混合文本计算，属于**近似值**；真实账单用量以 API 返回的 usage 为准，显示在综合控制台。

### 输入框与全局字号

- 输入框会从单行高度开始，随着 `Enter` 换行或文本自动换行逐行增高，最高约 150 px；清空后自动收回。
- 综合控制台右上角的「字号」控件可减小/增大全局字号，范围 80%–150%，每次 5%。
- 快捷键：`Ctrl+Shift++` 增大，`Ctrl+Shift+-` 减小；在输入框内也有效。
- 字号同时作用于侧栏、聊天气泡、Markdown、表格和控制台，并写入 `%APPDATA%\APIChat\config.json` 的 `font_scale`，下次启动自动恢复。

### 推理等级与在线搜索

输入框左下角有「思考」等级选择和「联网」开关，默认关闭。

**思考等级**

- 可选等级由当前模型类别决定：
  - OpenAI 兼容：关 / 低 / 中 / 高
  - Anthropic：关 / 低 / 中 / 高（映射为 thinking token 预算）
  - Gemini：关 / 低 / 中 / 高（映射为 thinkingBudget）
  - DeepSeek：关 / 高（reasoner 是单一推理模式；`deepseek-chat` 会自动切换为 `deepseek-reasoner`）
- OpenAI 使用 `reasoning_effort`；Anthropic 使用 `thinking`；Gemini 使用 `thinkingConfig`。
- 模型是否支持、是否计费以及是否返回思考文本，由服务商决定；不支持时会报错，请降低等级或关闭。
- 思考过程会以「▸ 思考过程」折叠框显示，正文仍是独立回答。

**搜索词提取与本地时间**

- 开启「联网」但关闭「思考」时，也会先用一次很小的模型请求，把聊天原文改写成更具体的搜索词；失败时回退到清洗后的问题原文。
- 例如“请帮我查一下当前日期时间”会被改写为更明确的搜索词，而不是直接搜索整段口语。
- 每次实际发给模型的用户消息都会临时加入当前本地系统时间（不写入数据库），因此“现在几点/今天几号”这类问题不需要依赖搜索结果中的过期时间。
- 搜索词提取请求也会计入 usage。

**搜索源**

综合控制台新增「搜索源优先级」配置块：

- 可添加 Bing、DuckDuckGo、SearXNG（需公网 HTTPS 地址）、Tavily（需 API Key）。
- 每个搜索源都有启用复选框：取消勾选后该源不参与搜索，但配置会保留。
- 可用 ↑/↓ 调整优先级，或删除不需要的源；配置会持久化。
- 开启「联网」后，按列表顺序调用**已启用**的搜索源并汇总结果，按 URL 去重。
- 单个源失败不会中断其他源；所有源都失败、或没有启用的源时显示错误。
- 搜索不会抓取结果网页，只解析标题、URL 和摘要。

**Tavily**

- 添加时选择「Tavily」并粘贴 API Key（以 `tvly-` 开头），可在 `https://app.tavily.com` 获取。
- 免费额度约每月 1000 credits；超出后按量计费。
- 选中列表项后可用「填 Key」更换 API Key。
- API Key 保存在本地 `%APPDATA%\APIChat\config.json`，界面只显示末 4 位。
- Tavily 返回结构化结果（标题、URL、摘要），比网页解析更稳定。

**推理 + 联网的组合行为**

同时开启「思考」和「联网」时，会进入有上限的推理/搜索循环：

1. 规划器先思考并决定搜索词；
2. 按优先级搜索并汇总外部资料；
3. 规划器阅读结果，评估置信度；
4. 若置信度低于 80% 且仍需信息，继续下一轮搜索；
5. 最多 3 轮，随后生成最终回答。

「置信度」是模型自评，不是严格统计值；循环有硬性上限，避免无限搜索和失控 API 费用。规划器请求也会计入 usage。

**安全策略**

- 只有手动打开「联网」才会发起搜索，不后台自动搜索。
- 内置源使用固定 HTTPS 地址；自定义 SearXNG 必须是公网 HTTPS，并拒绝 localhost、私有地址、链路本地地址和保留地址，降低 SSRF 风险。
- Tavily Key 仅随请求发送到 `https://api.tavily.com/search`，不做重定向跳转；界面和日志中只出现脱敏后的 Key。
- 结果 HTML 只按文本解析，丢弃标签、脚本、事件属性和危险协议 URL；限制查询、标题、摘要和结果数量。
- 搜索结果使用随机边界标记为**不可信外部资料**，提示模型不要执行其中指令；这降低但不能完全消除提示注入风险。
- 不抓取结果页面，不向搜索源发送本地对话或 API Key。
- 搜索词可能包含隐私信息，查询会离开本机；请勿搜索密码、密钥、私人身份信息。
- 搜索失败会明确报错，不会伪装成已搜索。

手机网页端同样提供等级选择和联网开关；手机端使用非流式请求，但推理过程和搜索结果同样会保存。

### 附件与图片

- 输入框左下角的回形针按钮可添加图片、PDF 或文本/代码文件；也可以直接把文件拖入输入框，或从剪贴板粘贴图片。
- 每条消息最多 6 个附件；默认图片单张上限 10 MB、文本附件 2 MB、PDF 20 MB，可在综合控制台的「附件上传上限」中调整（图片 1–50 MB、文本 1–20 MB、PDF 1–50 MB），桌面端和手机网页端同时生效。
- 图片会以缩略图显示在消息气泡中，点击可查看大图并保存原图；文本附件点击后可预览和保存。
- PDF 会提取可读文本作为带文件名标记的上下文发送，原 PDF 仍保存到附件表，预览时显示提取出的文本，保存时保存原文件。
- 扫描版/图片型 PDF 没有可提取文本，会提示不支持；可先把页面转为图片再作为图片附件发送。
- 图片会按所选 API 的协议转换为 OpenAI `image_url`、Anthropic `image` 或 Gemini `inline_data`；文本文件和 PDF 文本会作为上下文发送。
- 只有支持视觉输入的模型才能理解图片；PDF 文本则按普通文本处理。
- 导入的网页图片会尽量下载并保存到本地附件表，最多 20 张。

![附件与图片](docs/screenshot-attachments.png)

### 导入网页分享对话

点击「新建对话」右侧的「…」→「导入网页分享对话…」，有三种来源：

1. **分享链接**：直接粘贴公开的 ChatGPT / Claude / Gemini / DeepSeek 分享链接。DeepSeek 会调用其公开分享接口读取对话，无需登录。
2. **HTML 文件**：在浏览器中打开分享页，按 Ctrl+S 另存为 HTML 后导入。适合需要登录或由 JavaScript 动态渲染的页面。
3. **粘贴文本**：使用 `User: …` / `Assistant: …`、`用户：…` / `助手：…` 等标记粘贴对话。

导入会创建一段新对话，角色、正文和可下载图片会重整为本地消息格式；标题设为手动标题，不会被自动生成覆盖。导入后可直接在当前 API 下继续聊天。

![导入网页分享对话](docs/screenshot-import.png)

> 分享页结构会随平台更新；解析优先读取页面内嵌 JSON，再尝试常见 DOM 选择器和文本标记。若链接需要登录，请使用 HTML 文件或粘贴文本。

### 导出对话

在对话右上角「…」、左侧「…」菜单或对话卡片右键菜单中选择「导出为文本文件」。导出内容包含：

- 对话标题、API 别名、模型、创建时间和导出时间；
- 每条消息的角色、时间和完整文本；
- 附件类型、文件名、大小和图片尺寸。

文件使用 UTF-8 with BOM，Windows 记事本可直接打开。

### 修改消息并重新提交

- 用户消息右侧的铅笔按钮：可「仅保存修改」或「保存并重新提交」。
- 重新提交会删除该用户消息之后的所有消息，并从该消息重新请求模型。
- 助手消息也可编辑并保存；若要重新生成，建议编辑对应的用户消息后重新提交，避免历史中出现不自然的连续助手消息。
- 每次重新提交都会同步删除旧回复对应的用量事件，控制台会立即反映新的统计。

![修改并重新提交](docs/screenshot-edit.png)

### 自动标题

- 第一轮模型回复完成后，如果标题仍是「新对话」且标记为自动，客户端会用同一 API 异步生成标题。
- 标题栏可直接点击修改；修改后「自动标题」标记消失，不再被自动覆盖。
- 菜单中的「重新生成标题」可强制再生成一次，标题请求的 tokens 也会计入控制台。

### 综合控制台

- 左侧「综合控制台」查看当前数据库的总用量和分对话用量。
- 顶部卡片：API 总用量、输入 Tokens、输出 Tokens、API 请求数。
- 中部：对话用量排行（前 6 个对话）；下方是按对话和按 API 的明细表。
- 顶部「附件上传上限」可调整图片、文本和 PDF 单文件大小，设置会同时应用于桌面端与手机网页端，并写入本地配置。
- 双击对话行可回到该对话。
- 右上角「切换数据库」可选择本机 MySQL 中的其他数据库；数据库不存在时会自动创建表。默认仍是 `api_chat`。

![数据库设置](docs/screenshot-database.png)

### 局域网共享（手机 Web 页面）

左侧「局域网共享」打开设置：

- 设置监听端口和访问码，点击「启动共享」。
- 手机与电脑连接同一个 Wi-Fi，用手机浏览器打开窗口中显示的地址即可。
- 首次访问需要访问码；分享链接中已包含访问码。页面提供对话列表、消息查看、图片/文件附件、新建对话和继续聊天。
- 手机端发送消息会调用该对话绑定的 API，并将用户消息、助手回复和 usage 一起写入当前数据库；桌面端会同步刷新。
- 手机端消息支持 Markdown 渲染（标题、粗体、列表、代码块、表格和链接）；脚本和危险链接会被过滤。
- 手机端输入框左侧有「思考」等级选择、「联网」开关和回形针按钮；附件、思考过程和搜索结果都会保存到数据库。上传上限与综合控制台中的「附件上传上限」一致。
- 「停止共享」会同时关闭监听端口和已有浏览器连接，手机刷新后立即无法访问。
- 关闭设置窗口不会停止服务；需要停止时再次打开并点击「停止共享」。
- 电脑端关闭程序时会自动停止共享。
- Windows 防火墙首次可能询问是否允许 Python/APIChat 访问网络，请允许专用网络。

![局域网共享设置](docs/screenshot-share.png)

![手机端页面](docs/screenshot-mobile.png)

> 服务只监听局域网地址，不经过云端；访问码用于阻止同一局域网内的未授权访问。使用 HTTP 明文传输，请仅在可信 Wi-Fi 下开启。

## 数据与用量说明

- **对话数据**：`conversations`、`messages`。
- **附件**：`attachments`，保存原文件、缩略图、MIME、尺寸和 token 估算；删除消息/对话时级联清理。
- **API 配置**：`api_providers`（含 API Key、系统提示词）。
- **用量**：`usage_events`。`chat` 事件挂在具体助手消息上；`title` 事件没有 `message_id`，但仍属于该对话。
- 删除消息或截断历史时，通过外键级联删除对应 `chat` 事件；清空/删除对话会删除全部关联事件，因此控制台总量会同步减少。
- 控制台统计的是**当前数据库里仍然存在的对话用量**，不是服务商后台的历史账单。若需要保留历史账单，请不要删除对应对话，或另行导出。
- 标题生成属于额外 API 请求，也计入请求数、输入和输出 Tokens。
- 如果某个服务端不返回 usage，客户端会用文本估算补齐，并在消息底部标注为约值。

配置和日志位于：

```
%APPDATA%\APIChat\config.json    # 数据库连接、窗口位置、上次对话、字号、附件上限
%APPDATA%\APIChat\app.log        # 运行日志
```

## 项目结构

```
APIChat/
  app.py                     # 程序入口
  apichat/
    config.py                # JSON 配置
    db.py                    # MySQL 连接与建表
    repository.py            # 对话/消息/API/用量数据访问
    models.py                # 数据模型（含 Attachment）
    tokens.py                # token 估算、格式化
    llm.py                   # OpenAI / Anthropic / Gemini 适配、多模态与流式解析
    attachment_utils.py      # 图片/PDF/文本附件校验、缩略图、PDF 文本提取
    importer.py              # 分享链接 / HTML / 文本解析
    exporter.py              # 文本导出
    reasoning.py             # 按模型类别映射推理等级
    web_search.py            # 多搜索源、结果清洗与不可信内容边界
    agent.py                 # 推理/搜索/置信度评估循环
    lan_server.py            # 局域网 HTTP 服务与移动端页面
    workers.py               # QThread 工作线程
    ui/
      main_window.py         # 应用编排
      sidebar.py             # 对话列表、导入/导出/共享入口
      chat_page.py           # 对话页面、附件输入
      message_bubble.py      # 消息气泡、图片/文件展示
      attachment_preview.py  # 附件预览/保存
      dashboard_page.py      # 综合控制台
      api_dialog.py          # API 管理与编辑
      database_dialog.py     # 数据库设置
      edit_dialog.py         # 消息编辑
      import_dialog.py       # 网页对话导入
      share_dialog.py        # 局域网共享设置
      theme.py / icons.py    # 深色主题与矢量图标
  assets/                    # 应用图标与控件图标
  scripts/seed_demo.py       # 可选的演示数据（拒绝覆盖 api_chat）
  tests/                     # 数据库、协议、导入导出、LAN 测试
  APIChat.spec / build_exe.bat
```

## 开发与测试

```powershell
conda activate apichat
python -m unittest discover -s tests -v
```

- `tests/test_repository.py` 会创建临时 MySQL 数据库并在结束后删除，不会改动 `api_chat`；测试包含附件 token 和级联行为。
- `tests/test_llm.py` 启动本地假 HTTP 服务，测试 OpenAI SSE、Anthropic Messages、Gemini generateContent、多模态 payload 和错误信息，不需要真实 API Key。
- `tests/test_importer.py` 覆盖 ChatGPT JSON、Claude JSON、DOM、文本兜底、HTML 图片和导出格式。
- `tests/test_lan_server.py` 覆盖访问码、移动端页面、对话列表、附件下载、新建对话和手机端发送消息。
- `tests/test_lan_server.py` 还覆盖手机端附件上传、停止共享后的端口释放和 Markdown 输出。
- `tests/test_attachment_utils.py` 覆盖 PDF 文本提取、扫描件拒绝和 PDF 大小限制。
- `tests/test_web_search.py` 覆盖搜索结果解析、搜索源顺序/去重、启用开关、Tavily Key 脱敏、危险 URL 过滤和不可信内容边界。
- `tests/test_llm.py` 还覆盖推理等级参数和推理内容流式解析。
- `tests/test_agent.py` 覆盖思考/搜索循环的置信度停止条件和最终上下文注入。
- `tests/test_reasoning.py` 覆盖不同模型类别的推理等级映射。
- `tests/test_query_planner.py` 覆盖搜索词提取、清洗、失败回退和本地时间注入。
- 当前共 47 个测试。
- 可选的演示数据：

  ```powershell
  python scripts/seed_demo.py api_chat_demo
  ```

  该脚本会拒绝写入默认的 `api_chat` 数据库。

## 打包

```powershell
build_exe.bat
```

等价于：

```powershell
conda activate apichat
python -m pip install pyinstaller
pyinstaller --noconfirm --clean APIChat.spec
```

输出为单目录应用 `dist\APIChat`，其中 `APIChat.exe` 为入口。`assets` 会打包进 `_internal\assets`。

## 常见问题

**无法连接 MySQL / 服务未启动**

```powershell
Get-Service MySQL
Start-Service MySQL
mysql -u root -h 127.0.0.1
```

也可以在程序的「数据库设置」中改用其他主机、端口或账号。

**创建 conda 环境时连接失败**

若公司网络无法访问 conda 默认源，可先尝试：

```powershell
conda create -n apichat python=3.11 -y --offline
```

若本机缓存里没有 Python 3.11，可改用镜像源，或在已能联网的环境创建后迁移。

**程序卡顿，任务栏/资源管理器也失去响应**

从 v1.4.1 起做了两处隔离：

- 文件选择/保存默认使用 Qt 内置对话框，不再调用 Windows Shell 的文件对话框，避免第三方 Shell 扩展把资源管理器一起拖死。
- 默认使用软件渲染，避免 Qt 的 D3D 初始化与部分显卡/虚拟显示器驱动冲突；如确认需要硬件渲染，可在启动前设置环境变量 `QT_OPENGL=desktop`。

排查步骤：

1. 查看 `%APPDATA%\APIChat\app.log`，搜索 `UI thread blocked`。出现该记录时，日志会附带主线程调用栈，可定位是哪一步阻塞。
2. 查看 `%APPDATA%\APIChat\crash.log`，这是 Qt/Python 原生崩溃日志，和 `app.log` 一起反馈。
3. 如果 Windows 事件查看器同时出现 `ShellExperienceHost.exe` 或 `explorer.exe` 挂起，优先更新/回滚显卡驱动，并且临时禁用虚拟显示器驱动（部分远程桌面、投屏软件会安装此类驱动），再观察是否只在使用本程序时复现。
4. 以管理员身份运行：

   ```powershell
   sfc /scannow
   DISM /Online /Cleanup-Image /RestoreHealth
   ```

5. 如果问题只在打开文件选择框后出现，确认使用的是 v1.4.1 或更高版本；旧版本会走 Windows 原生对话框。

**401 / 403 / 404**

- 401：检查 API Key 是否有效。
- 403：检查账号额度、模型权限或地区限制。
- 404：检查 Base URL 是否少了 `/v1`，以及模型 ID 是否存在。
- 错误详情会显示在对话底部的错误条中，可点「重试」。

**流式回复不显示 / 网关不支持 `stream_options`**

客户端会自动对部分 400 错误做一次无 `stream_options` 的重试。如果服务商只支持非流式接口，请换用兼容 OpenAI Chat Completions 的地址，或使用支持 SSE 的网关。

**上下文百分比和账单不一致**

百分比是估算值，且不包含服务端的隐藏系统 token；账单以控制台的 API usage 为准。

## 安全说明

- API Key 以明文保存在本地 MySQL 的 `api_providers.api_key` 字段中；数据库密码以明文保存在 `%APPDATA%\APIChat\config.json`。请只在可信的本地电脑上使用，并妥善保护 MySQL 账号。
- 默认情况下，程序只把对话发送给所配置的模型 API，不会上传到其他服务，也没有遥测。
- 只有手动打开「联网」时，当前问题才会发送给 Bing 搜索；搜索结果按不可信外部数据处理，不抓取结果页面。请勿用联网模式搜索密码、密钥、私人身份信息等敏感内容。搜索摘要可能不准确，引用前请核对原始来源。
- 局域网共享使用随机访问码校验，但传输层是 **HTTP 明文**。同一 Wi-Fi 下的其他设备或网络监听者可能看到内容，请只在可信网络中临时开启，用完即停止。
- 共享服务会暴露当前数据库中的全部对话；不要在包含敏感内容的数据库中长时间开启。
- 导入网页时，程序会访问用户填写的公开 URL；请只导入自己信任的链接。
- 如果多人共用电脑，建议为 MySQL 创建独立账号，并使用 Windows 文件权限保护配置目录。

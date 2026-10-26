# frontend — React + Vite

OcuPanel 的浏览器客户端。浅色三栏：左侧导航（会话列表）+ 主内容区 + 右下角调试抽屉。
项目整体介绍与使用说明见 [根目录 README](../README.md)。

```bash
npm install
npm run dev          # 开发：5500，/api 代理到 8000
npm run build        # 产出 dist/，由 FastAPI 直接托管
```

> 没有 `npm start` 这个脚本，别试。

---

## 技术栈

React 18 + Vite 6，没有路由库、没有状态管理库、没有 UI 组件库。
Markdown 渲染用 Showdown（**已显式开启 `tables: true`**，默认是关的，表格会渲染成一行竖线）。

## 目录与组件

```
src/
├── main.jsx                     # 挂载入口
├── App.jsx                      # 全局状态与业务逻辑（登录态、会话、视图切换）
├── api.js                       # 接口封装：统一带 Bearer 令牌，401 自动退回登录
├── debug.js                     # 调试记录的收集与订阅
├── styles.css                   # 全部样式（单文件，无 CSS-in-JS）
└── components/
    ├── LoginPage.jsx            # 登录 / 注册（同卡片切换）
    ├── Sidebar.jsx              # 会话列表 + 新建对话 + 生成报告 + 底部用户区
    ├── WelcomeView.jsx          # 欢迎页（建议卡，无输入框）
    ├── ChatView.jsx             # 对话消息流 + 输入框
    ├── ReportView.jsx           # 上传眼底图 + 临床记录 + 生成
    ├── SettingsView.jsx         # 个人设置：LLM 配置 / 用量 / 退出登录
    ├── EvidenceList.jsx         # 证据包卡片（可展开看三个原始分）
    ├── VerificationResult.jsx   # 引用校验结果条
    ├── Markdown.jsx             # Showdown 渲染 + 表格横向滚动容器
    ├── LoadingOverlay.jsx       # 长任务遮罩
    └── DebugDrawer.jsx          # 右下角调试抽屉
```

## 页面状态约定

主视图状态是 `App.jsx` 里的 `view`，四种取值：`'welcome' | 'chat' | 'report' | 'settings'`。

- **欢迎页只在首次登录 / 无对话时出现**，它没有输入框，只是引导。点「新建对话」必须进
  `ChatView`（`setView('chat')`），删除当前会话后同理——**绝不能把用户丢回欢迎页**，
  否则看起来像按钮没反应。
- **退出登录有两个入口**：侧栏底部的图标（`.nav-user-logout`）与「个人设置」里的按钮，
  都要走 `handleLogout`（confirm → `/account/logout` → resetToLogin）。
- `.nav-user` 是 `<div>` 容器而非 button（内部有两个按钮 `.nav-user-main` / `.nav-user-logout`），
  改结构时注意别嵌套 button。
- 侧栏「用户区」不是纯展示：点名字进设置页。

## 界面功能

**1. 登录 / 注册** — 用户名 + 密码，同一张卡片切换。登录态是随机令牌（存 SQLite `sessions`，
7 天有效），不是 JWT，所以注销能真正失效。退出只清除本机登录态，**服务端数据一条都不动**，
重新登录后对话与报告都还在。

**2. 对话（智能问答）**

- 首页是带建议卡的欢迎页，点卡片直接把问题发出去；
- 对话记录存在服务端，换设备登录也还在，重启服务不丢；
- 首条消息自动给会话起名，侧边栏不再一水儿「新对话」；
- 每个账号只能看到自己的会话，访问别人的会话一律 404。

**3. 生成报告**

- 左栏点「生成报告」进入，上传眼底图（支持拖拽）+ 填临床记录；
- 触发完整链路：分割 → 分类 → 六专科并发 → Director 综合 → 引用校验；
- 结果**追加到当前对话**，所以生成完可以直接接着追问（报告正文本身就是上下文）；
- 校验不通过时后端拒答、不出 PDF，前端不显示「下载」按钮；
- 通过后可下载含图像、杯盘比与完整报告的中文 PDF。

**4. 个人设置**

- 填 API Key / 接口地址 / 模型，内置 DeepSeek、OpenAI、Moonshot、阿里云百炼四家预设；
- 「测试连通」先用一次最小请求验证 key / 端点 / 模型，**测通了再保存**，
  避免错配置存进去之后每次生成都失败；
- Key 服务端加密存储，界面只显示掩码，留空保存表示沿用旧值；
- 显示使用概况：几个对话、几份报告、其中几次因校验未通过被拒答。

## 调试抽屉

右下角「调试」悬浮按钮（`DebugDrawer.jsx`），点开能看到最近 50 次请求：

| 字段 | 说明 |
|---|---|
| 名称 / 方法 / URL | 如「生成报告内容 · POST /api/generate-report-content/」 |
| 状态与耗时 | `200`、`ERR`（网络失败）与毫秒数 |
| 请求 | 文件名、大小、备注字数 |
| 响应 | 原始 JSON（截断 4000 字符）或 Blob 大小与类型 |

支持「复制」把全部记录导出成 JSON。

URL 参数 `?debug=0` 可隐藏调试按钮（给医生演示时用），也可以写进 `.env` 的 `VITE_DEBUG=0`，
**不需要重新构建**。

> 离线 mock 模式已移除。数据现在都在 SQLite 且需要登录态，
> 留一个假的 mock 层只会在排查时制造「看起来通了其实没通」的错觉。

## 环境变量

`frontend/.env`（模板见 `.env.example`，一般不用配）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | 空（同源相对路径） | 只有后端在别的地址 / 端口时才需要设置 |
| `VITE_DEBUG` | `1`（开启） | 右下角调试抽屉 |

## 已知坑

**页面能打开，但一提交就 `Internal Server Error`。** 开发模式下页面在 5500、接口要转发到 8000，
只起前端时页面正常（纯静态），但任何提交都会因为代理找不到后端而失败——
Vite 会返回 `500` + `text/plain` + **空响应体**，浏览器只显示一句 Internal Server Error。

`api.js` 已针对这个形态给了可读提示。判断方法：

```bash
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/account/llm-presets
```

返回 `200` 说明后端在跑（去看它的 traceback）；连接失败说明后端没起。

**改了代码页面没变化。** 单服务模式下页面来自构建产物，改完要重新 `npm run build`；
想热更新就用 `npm run dev`。

**端口被占用（WinError 10013）。** 后端设 `PORT=8001`，前端设
`VITE_API_BASE_URL=http://127.0.0.1:8001`。

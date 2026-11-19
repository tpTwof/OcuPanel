# OcuPanel

## 项目简介

OcuPanel 是一个基于 React 和 FastAPI 的眼科问答与眼底影像分析项目，适用于眼科 AI 演示、研究和二次开发。它提供普通聊天、眼科助手问答和影像报告三种入口。提交彩色眼底照片和临床记录后，系统执行视觉分析、按病种检索和撰稿、按需综合及引用校验。

青光眼分析可输出分类概率、视杯视盘分割图和面积等效杯盘比。示例数据用于演示，报告仅供研究和开发参考。引用校验核查外部知识陈述的出处，临床结论仍需专业人员判断。

本地工作区另有 DR（糖尿病视网膜病变）和 AMD（年龄相关性黄斑变性）的 FLAIR 研究性图文匹配、GraphRAG 和历史报告导出。FLAIR 缺少影像质量判断、临床阈值和独立病例验证，暂用于研究评估。[可选依赖](backend/vision/README.md#糖网与年龄相关性黄斑变性) · [模型验证计划](docs/research/retinal-disease-model-selection.md#当前实现的缺陷) · [图检索配置](backend/README.md#graphrag)

## 安装指南

以下命令以 Windows PowerShell 和 CPU 环境为例。准备 Git、Python 3.13 和 Node.js（含 npm）。前端开发环境使用 Node.js 24.15.0 / npm 11.12.1，模型权重通过 Hugging Face 下载。Linux 服务器安装见 [部署指南](docs/DEPLOY.md)。

1. 克隆仓库并进入项目目录。

   ```powershell
   git clone https://github.com/tpTwof/OcuPanel.git
   Set-Location OcuPanel
   ```

2. 创建 Python 虚拟环境，先安装 CPU 版 PyTorch，再安装后端依赖。

   ```powershell
   py -3.13 -m venv .venv
   $projectPython = '.\.venv\Scripts\python.exe'
   & $projectPython -m pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu
   & $projectPython -m pip install -r .\backend\requirements.txt
   ```

   如果 Python Launcher 未注册 3.13，可使用独立安装的 Python 3.13 可执行文件完整路径运行 `-m venv .venv`。

3. 按锁文件安装前端依赖、构建页面，并初始化后端配置。

   ```powershell
   npm.cmd --prefix frontend ci
   npm.cmd --prefix frontend run build
   if (-not (Test-Path .\backend\.env)) {
       Copy-Item .\backend\.env.example .\backend\.env
   }
   ```

## 使用说明

在仓库根目录运行以下命令，并打开 [本地页面](http://127.0.0.1:8000)。FastAPI 同时托管前端和 API。

```powershell
.\.venv\Scripts\python.exe .\backend\main.py
```

1. 注册或登录。在「个人设置」填写自己的 LLM API Key、接口地址和模型，测试连通后保存。
2. 点击「新建对话」开始普通聊天，或切换到「眼科助手」进行眼科问答。
3. 点击「眼科分析」，上传 [示例眼底照](samples/fundus_right_eye.png)，并将 [示例临床记录](samples/clinical_note.txt) 的内容填入表单。点击「生成报告」。
4. 在当前对话中查看报告、叠加图和引用证据。通过校验的报告可下载 PDF。拒答时可在界面查看原因。

首次分析可能下载模型权重。开发时可运行 Vite 热更新，详见 [前端 README](frontend/README.md)。服务启动后可访问 [Swagger UI](http://127.0.0.1:8000/docs) 查看 API。

## 配置

服务端配置位于 [`backend/.env.example`](backend/.env.example) 对应的本地 `backend/.env`，修改后重启服务。

| 配置项 | 示例 | 用途 |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | 后端监听地址 |
| `REPORT_LANGUAGE` | `zh` 或 `en` | 报告正文与 PDF 标签语言 |
| `REPORT_FONT_PATH` | `C:/Windows/Fonts/simhei.ttf` | 指定本机已有的中文 PDF 字体 |
| `RAG_MODE` | `hybrid` | 报告检索方式。可选 `bm25`、`vector`、`hybrid` |
| `HF_ENDPOINT` / `HF_HOME` | 按下载源和缓存位置填写 | 模型下载地址与本地缓存根目录 |

每个账号在「个人设置」保存自己的 LLM 凭据。部署和迁移时需要保留 SQLite 数据库、加密密钥和分割图。完整配置与数据路径见 [后端 README](backend/README.md#配置)。

## 目录与文档

| 目录 | 内容 |
| --- | --- |
| [`backend/`](backend/README.md) | FastAPI、账号与会话、视觉模型、报告和引用校验 |
| [`frontend/`](frontend/README.md) | React 页面、Vite 开发模式、接口与调试 |
| [`docs/`](docs/README.md) | 架构、数据对象、部署和研究记录 |
| [`samples/`](samples/README.md) | 示例眼底照、临床记录与报告 |
| [`tools/`](tools/README.md) | 账号隔离检查与界面截图工具 |

## 贡献指南

1. Fork 项目并克隆自己的 Fork。
2. 从最新的 `main` 创建分支，例如 `git switch -c feature/your-change`。
3. 修改代码和相关模块 README，按改动范围运行后端测试或前端构建。

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s backend/tests
   npm.cmd --prefix frontend run build
   ```

4. 使用 `git add` 暂存本次变更，然后执行 `git commit -m "docs: update project guide"`。
5. 执行 `git push -u origin feature/your-change`，向上游 `main` 提交 Pull Request。

项目的业务演进见 [版本记录](update/README.md)。

## 许可证

本项目采用 MIT 许可证。[LICENSE](LICENSE) 保留了上游 M2-Lab@Purdue 的版权声明。

## 上游项目与致谢

OcuPanel 最初 fork 自 Purdue M2 Lab 的 MedChat。MedChat 以青光眼为主，OcuPanel 将其报告流程扩展到多种眼病。每个所选病种生成一份分析，选择多个病种时由 Director 汇总专科意见。OcuPanel 在此基础上加入了多用户账户、SQLite 持久化、证据检索和引用校验。感谢 MedChat 作者及贡献者公开原始实现。 [上游仓库](https://github.com/Purdue-M2/MedChat) · [原始论文](https://doi.org/10.1109/MIPR67560.2025.00078) · [BibTeX](docs/README.md#引用)

## 联系方式

- 邮箱 <tptwo06@gmail.com>
- GitHub [@tpTwof](https://github.com/tpTwof)
- 问题反馈 [OcuPanel Issues](https://github.com/tpTwof/OcuPanel/issues)

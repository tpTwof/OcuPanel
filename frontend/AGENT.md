# 前端约定

页面状态、组件职责和开发方式见 [README.md](README.md)。

- `src/App.jsx` 管理全局视图与会话状态，`src/api.js` 统一处理请求、Bearer 令牌和 401；组件通过现有入口接入。
- 保持前后端 URL、multipart 字段、JSON 字段和报告拒答状态一致；下载报告只面向已保存且通过校验的结果。
- 修改交互时检查新建与删除会话后的视图、两种聊天形态、退出登录入口和请求中的重复提交状态。
- 页面改动后运行 `npm.cmd --prefix frontend run build`；在其他系统使用 `npm`。

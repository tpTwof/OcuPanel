# 开发工具

以下命令从仓库根目录运行，使用 [安装指南](../README.md#安装指南) 创建的虚拟环境。

## 账号隔离自检

启动本地后端后运行以下命令。脚本创建两个临时注册账号，检查认证与跨账号会话访问等行为，失败时返回非零退出码。`--cleanup` 直接操作本机 `backend/ocupanel.db` 清除临时账号，仅用于本机同一份数据库上的实例。

```powershell
.\.venv\Scripts\python.exe .\tools\check_isolation.py --base http://127.0.0.1:8000 --cleanup
```

## 界面截图

`shot.py` 使用标准库通过 Chrome DevTools Protocol 驱动无头 Chrome。脚本使用 Windows 的默认 Chrome 安装路径和调试端口 `9333`。下面的例子保存本地服务首页的截图。

```powershell
.\.venv\Scripts\python.exe .\tools\shot.py http://127.0.0.1:8000 ocupanel-home.png --width 1440 --height 900
```

可选参数包括等待时间、点击选择器和输入文字，详见 [脚本说明](shot.py)。

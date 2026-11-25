# 开发工具

## 病例工作台独立验收

先构建前端，然后运行 `.\.venv\Scripts\python.exe tools/serve_screening_acceptance.py --port 8127`。仅监听 127.0.0.1，在仓库 tmp 下创建一次性的合成账号、数据库、原图和存档，浏览器首页注入该临时账号的令牌，不使用生产数据库或真实 Key。退出进程后可清理对应临时目录。包含双眼不同结果、有原图新报告、缺原图历史报告及拒答记录；可用来重放[问题复核及导入验收](../docs/病例工作台导入实现与二次验收.md)。测试图像和模型输出都是合成固定值，不评估医学效果。

## 阅片方法配对评估

无需模型、联网或 LLM，输入为 JSON `{manifest, rows}`。先用合成示例验证计算；该示例不能评估临床性能。

```powershell
.\.venv\Scripts\python.exe tools/evaluate_screening.py tools/screening-evaluation.example.json --output screening-evaluation.json
```

`manifest` 必须包含 `old_version`、`candidate_version`、`reference_standard`、`locked_workpoints`、`dataset_version`，实际评估时填写固定版本、校准集选点依据和参考标准。`rows` 每行包含患者、就诊、眼别、任务、机构、设备、分组、参考标签与同例新旧决定，字段见示例。分组为 development / calibration / test，患者跨组直接报错，只计算 test 集。模型决定为 refer / no_refer / abstain，参考标签为 refer / no_refer / unknown，最终流程决定用可选的 `old_workflow` / `candidate_workflow` 登记 refer / no_refer / pending（默认）。这两个字段反映人工接手后的实际转出，不能由模型分数推测。

输出逐病种及机构、设备分层结果，包含有决定病例的灵敏度和特异度、混淆计数、弃判、覆盖率、复核量、未知参考结局与患者整组 bootstrap 95% 区间及配对差值。流程漏转率使用参考标准确认应转者为分母，去向未决则返回上下界。未知参考结局不计为阴性。`--bootstrap` 可选 100–10000，默认 1000；同输入可复现。需要另行完成独立机构验证、质控和分割评价、抽样核验校正及事前统计方案。

## 冻结本地旧模型

把已取得授权的分类、分割及处理器完整文件放入专用目录，提供实际元数据 JSON，再生成文件清单。工具不下载、不复制权重，也不修改模型选择。

```powershell
.\.venv\Scripts\python.exe tools/freeze_vision_baseline.py LOCAL_ARTIFACT_DIRECTORY --description baseline-description.json --output baseline-manifest.json
```

说明文件必填 `classification_revision`、`segmentation_revision`（均为固定的 40 位提交哈希）、`class_order`、`mask_semantics`、`processor`、`cdr_definition`。分类现实现使用索引 1 作为青光眼，分割为 0 背景、1 视盘环、2 视杯；CDR 定义为 `sqrt(cup_area / (disc_ring_area + cup_area))`，需结合实际模型文件核对。附加记录模型来源、代码与权重许可、训练数据来源及样例输出。输出为逐文件字节数和 SHA-256，不代表验证通过。输出文件必须位于权重目录外，避免重复冻结时把上次清单算作权重。

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

## 机构演练与运行维护

在仓库根目录使用项目 Python。示例仅含虚构机构、成员名、检查结果。先在演练实例注册示例中的三个账号，再配置名单。配置写入当前应用数据库，原子替换该机构的全部成员和策略。允许端点为空时，机构成员不能通过账号配置调用任何 LLM 端点。暂停开关影响新分析及尚未执行的排队任务，已开始的外部调用会继续执行。

~~~powershell
python tools/configure_screening_site.py tools/screening-site.example.json
python tools/evaluate_screening.py tools/screening-evaluation.example.json --output evaluation.json
python tools/screening_operations.py Demo --start 2026-11-24T00:00:00+08:00 --end 2026-11-26T00:00:00+08:00
~~~

运营统计按提交时间计入区间内的机构队列任务，等待 P95 仅含已开始任务，端到端 P95 仅含已结束任务。按患者分组号去重统计转诊与到诊，模拟签发次数包含后来撤销的签发事件。可选 `--total-cost` 填入同期成本，`--model-version` 返回匹配版本的归档报告号。旧同步接口调用没有队列计时。评估样例包含抽中、未抽中、弃判和未知结局；抽中的参考结果缺失时不输出加权漏转点估计。

停写并停止服务后，备份到源目录之外尚不存在的新目录，恢复到另一个新目录。命令中的父目录须已存在。工具覆盖数据库、原图和叠加图，并校验文件清单、SHA-256 和 SQLite 完整性。加密密钥由部署方独立备份，在隔离环境恢复时使用原密钥。备份中可能包含未处理任务的输入，存取权限和留存期限须覆盖整个快照。

~~~powershell
python tools/archive_maintenance.py backup backend ../ocupanel-snapshot
python tools/archive_maintenance.py restore ../ocupanel-snapshot ../ocupanel-restored
python tools/archive_maintenance.py expire ../ocupanel-restored --days 30
~~~

最后一条仅预览。经本地确认留存期后加 `--apply` 才删除到期原图；服务端可用 `ORIGINAL_RETENTION_DAYS` 启用启动时和每日清理（0 为关闭）。清理按报告创建时间计算，保留报告、已有审计和原图摘要。示例的 30 天仅用于演练。

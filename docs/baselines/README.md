# 青光眼旧方法基线

这些文件由本机已有 Hugging Face 快照生成，不下载或再分发权重，不声明临床有效性。固定提交与本项目实际标签及预处理配置对应：

| 角色 | 仓库 | 固定提交 |
| --- | --- | --- |
| 分类 | `pamixsun/swinv2_tiny_for_glaucoma_classification` | `a25a03d9ff23d6fbaf6cd7a329373253f4671c63` |
| 分割 | `pamixsun/segformer_for_optic_disc_cup_segmentation` | `a0463fb6c2bf184cf398e5fd82a8194e01e66e7f` |

`baseline-description.json` 保存类别顺序、掩膜语义、实际处理器配置和面积等效 CDR 定义。`classification-manifest.json` 与 `segmentation-manifest.json` 保存对应快照每个文件的字节数和 SHA-256。缓存中的符号链接按实际文件内容计算哈希，清单不保存个人缓存绝对路径。两份模型卡文件也列入哈希，许可与预期用途仍需另行审查。

`sample-output.json` 来自固定提交对 `samples/fundus_right_eye.png` 的真实 CPU 离线推理，包含原图哈希、环境版本、分类概率、面积等效 CDR、掩膜形状、像素计数和掩膜哈希。这张仓库图片带 AI 生成标记，只验证执行及回归行为。输出与原模块 README 中既有数值一致；合成单元回放另见 `backend/tests/test_glaucoma_cases.py`。

后续改版时保留此目录作为旧方法对照，为新版本新增清单和配对评估记录。不同运行库、设备的浮点与掩膜差异须按事前误差容许范围解释。尚未提供候选权重、患者标签、独立测试集、临床工作点或正式放行依据。

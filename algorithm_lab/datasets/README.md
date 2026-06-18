# Datasets

这里存放算法实验用评测集。建议使用 JSONL，避免和主业务数据库耦合。

第一阶段建议只做小而准的会议检索评测集：

- 每个样本 1 个用户问题。
- 至少标注 `relevant_note_ids` 或 `relevant_keywords`。
- 关键样本逐步补充 `relevant_chunk_ids`。

不要直接把全部会议原文复制到这里。会议原文仍然保留在 SQLite，评测集只保存问题和标注。

# 成员 B · Hadoop Streaming / Spark SQL 统计作业（阶段二）

本目录是可执行的计算源码，不是模拟 MapReduce/Spark 的普通 Python 重算脚本。使用前，请先阅读根目录 `AGENTS.md`、`docx/data-contract.md`、`docx/environment.md`。提交前务必与 A 侧现有工作树和锁定环境同步。

## 已实现与尚未验证

- `analysis/mapreduce/mapper.py` / `reducer.py`：读取标准 21 列 CSV 物理行，通过 Streaming shuffle/reduce 对城市和等级分别计数，保留 null 分组和 conflict/unknown 状态。
- `analysis/spark/job.py`：从 HDFS 标准 CSV 用显式 Decimal schema 读取，实际使用 Spark SQL 计算 all、province、city、grade、city_grade、type 数量及数据质量；在字典有已批准政策时按币种、政策分组生成价格汇总和直方图，没有政策时 `pending_policy`。
- `analysis/runner.py`：运行前读回校验 HDFS CSV、manifest、字典 SHA-256；生成独立 `runs/<run_id>/.../raw`，将原生引擎结果转换到 `data/results/<batch>/<engine>/statistics.jsonl` 与 `run.json`，不覆盖已有选定产物。
- `analysis.runner reconcile`：重新验证 HDFS 身份，同批次 MapReduce 与 Spark SQL 城市/等级分组逐组核对，写入 reconciliation.json；此对账**不自动将数据库批次置为 ready**。
- 单元测试和模拟 Streaming stdin/stdout 已通过；尚未在本环境运行 Hadoop/YARN、PySpark 及真实批次。现有运行代码仍需在 Codex 的实际 WSL + 项目锁定环境审查验收。

## 在已就绪的项目工作树中运行

环境须是 `docx/environment.md` 中指定基线，已有 .venv、HDFS、YARN、有效批次与配置；**不要为了运行脚本而重新格式化 NameNode 或覆写批次**。

```bash
export JAVA_HOME='/path/to/jdk11'
export HADOOP_HOME='/path/to/hadoop-3.4.3'
export HADOOP_CONF_DIR='/path/to/tourism/.runtime/hadoop/conf'
export HDFS_URI='hdfs://localhost:9000'
export HDFS_ROOT='/tourism'

# 原 HDFS input 与 metadata 必须已存在且摘要匹配；下面每次使用全新 run_id。
sh scripts/run-mapreduce.sh --batch-id atlas_clean_20261102_02 --run-id b_mr_01
sh scripts/run-spark.sh --batch-id atlas_clean_20261102_02 --run-id b_spark_01
sh scripts/reconcile-statistics.sh --batch-id atlas_clean_20261102_02
```

不要直接复用上述示例 run_id：先查明 HDFS 中是否已存在相应目录，再选择新 ID。运行前需 `uv sync --locked --all-groups` 并由 A 恢复真实批次与 Hadoop 服务。实际路径从当前工作树取得，不在共享源码内硬编码用户名/密钥。

**安全约束：** 代码只读输入与元数据，仅在独立的 run 目录和本地 `data/results`、`.runtime` 中写入。无法取得真实快照、SHA 失配、价格政策格式错误、运行异常、输出非预期或 YARN 应用未成功时停止；不生成成功状态的 `run.json`。已有本地结果不自动覆盖。未执行的运行不得伪称成功。

**环境依赖：** Spark 程序需要 PySpark 3.5.8，流式作业需要 Hadoop Streaming 3.4.3 与可用 YARN。统计输入约定是物理单行 CSV（引号、逗号由 CSV/Spark 解析），不是随意换行的 CSV。单元测试不能代替真实 Spark SQL/YARN 作业证据。

## 交给 A/C 的产物

- `data/results/<batch>/mapreduce/statistics.jsonl`、`run.json`
- `data/results/<batch>/spark_sql/statistics.jsonl`、`run.json`
- `data/results/<batch>/reconciliation.json`

请由 A 核查完整来源与运行证据、价格政策、所有必需分组及数据完整性，按既有数据库导入流程导入并决定批次状态。C 对外图表只读 Spark 结果，MapReduce 只作独立对账，不能两者相加。

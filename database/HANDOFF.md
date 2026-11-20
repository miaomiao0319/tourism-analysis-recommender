# A 数据接入交接

本说明记录当前实现与复现入口，字段和状态以项目数据、接口及环境契约为准。

## HDFS 输入与验证

已在单机伪分布式 Hadoop 3.4.3 上验证真实批次 `atlas_clean_20261102_02`，其标准数据位于：

```text
hdfs://localhost:9000/tourism/batches/atlas_clean_20261102_02/input/attractions.csv
hdfs://localhost:9000/tourism/batches/atlas_clean_20261102_02/metadata/manifest.json
hdfs://localhost:9000/tourism/batches/atlas_clean_20261102_02/metadata/dictionaries.json
```

CSV、清单及字典上传后均已读回核对SHA-256；景点数量8431，涵盖31省级地区，价格符合当前政策者2条。候选记录不等于全国全部景点，也不保证每个地点当前对游客开放。源数据的公开分发限制见批次内来源记录。

配置入口为 `scripts/hadoop.sh` 和WSL挂载包装器 `scripts/hadoop-wsl.sh`；执行前按环境规范提供已安装的 `JAVA_HOME` 与 `HADOOP_HOME`。使用已初始化运行目录时只能执行start/status/stop；不要再次format。`status`检查DataNode、NodeManager与独立文件读写。上传入口为 `scripts/upload-hdfs.py --batch-id <id>`，需提供 `HADOOP_CONF_DIR`、`JAVA_HOME` 和 `HADOOP_HOME`。本机挂载启动、一次停止再启动及批次读回已验证；整机/WSL重启恢复仍未验证。

同批真实 MapReduce 和 Spark SQL 结果及对账记录保存在本机审核工作树的 data/results 中；YARN 状态与 HDFS 原始输出已核对。本文件不代表已通知B。

A的 `database/statistics_check.py` 已提供两项初步检查：核对两个运行记录的批次、引擎、契约版本和输入SHA-256；对城市及等级计数做逐组和总数对账。其返回值明确标示并非完整运行审计，也不能授权导入或切换ready。其他必需统计、价格口径、来源和数据库状态仍须另行验证。

`check_required_count_groups(standard_rows, mapreduce, spark, batch_id)` 从已验证标准行重新计算 MapReduce 的城市/等级及 Spark 的总体/省份/城市/等级/城市等级数量，检查每组完整性和数量。它不检查类型、价格、作业真实性或数据库。`verify_local_standard_file(path, manifest)` 检查本地文件字节摘要，不证明引擎实际读取了该文件。

`check_data_quality(standard_rows, spark_records, batch_id)` 可将 Spark 的单条 `data_quality` 与已预检的标准数据逐项对照；标准行的 `type_codes` 须先解析为数组。调用方仍须独立验证文件摘要、运行出处及其他指标；该检查不会导入数据或发布批次。

`check_overall_price_summary(standard_rows, spark_records, batch_id, currency, policy_id, group=None)` 可对单个已核准政策的总体、城市或等级价格汇总进行只读对账；默认总体，城市及等级通过 `group` 传入契约维度。调用前须完成标准数据、来源证据及政策批准的独立验证；一次仅核对指定分组，不代表所有分组已齐全或统计可导入。

`check_overall_price_histogram(standard_rows, spark_records, batch_id, currency, policy_id, group=None)` 对指定总体、城市或等级分组的价格直方图进行只读对账，验证 B 选择的分箱边界和逐箱数量；同样须独立验证来源、政策及输入。`check_pending_price_policy(spark_records, batch_id, metric, approved_policies)` 检查一条总体政策待定记录；调用前须独立核实无已批准政策并传入空列表。不能用空字典或未经审核的政策清单替代批准核实。

## 查询接入

统计导入入口为 `python -m database.import_statistics <batch_id> <results_root>`，其中 results_root 包含批次目录和 mapreduce、spark_sql 子目录。先提供 Hadoop 与 HDFS 配置及 DB_IMPORT_USER、DB_IMPORT_PASSWORD，连接参数沿用景点导入。程序校验本地批次、HDFS 输入和两引擎原始输出，独立对账数量、类型、质量及全部价格分组，再锁定数据库批次并事务式写入统计。已有统计相同则幂等返回，不同则拒绝覆盖；入口保持批次原状态，不自动发布 ready。运行记录和 HDFS 当前内容相符不能单独证明历史运行时输入未变化。

`backend.app.repositories.attractions.AttractionRepository`接收无参数据库连接工厂，提供批次、列表、详情、统计和完整推荐候选读取。调用者负责提供只读连接与UTC会话。只有明确指定的ready批次可读；本机真实批次 `atlas_clean_20261102_02` 已在2026-11-20导入统计并核验后置为ready。

`backend.app.repositories.error_adapter.RepositoryAdapter`可接收C实现的`AppError`类及数据库连接异常类型。C负责公共错误类型和HTTP映射；当前适配器仅用替身及独立测试库验证，尚未与Flask或C的模块联调。候选迭代器应完整消费或显式关闭；SQL中途失败应终止整次推荐。

本机`tourism_reader`仅允许Linux用户通过本地Unix socket读取项目库，不是可跨机器复用的账户；部署时应按环境约定建立只读账号，切勿把凭据写入仓库。构造MySQL验证库与真实loading批次相互独立。

## 当前交付限制

- Python 3.11数据依赖、查询及保护测试已在本机运行；其他角色依赖组尚待相应角色验证。
- 本机真实批次已导入两引擎共2276条统计；只读账户已验证查询、统计及推荐模块接入。HTTP接口和网页尚待C交付并联调。
- 同步远端和公开数据必须按项目Git及来源使用边界处理。

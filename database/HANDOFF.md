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

B应使用同一批次与配置运行项目MapReduce和Spark SQL，保留实际输入SHA-256、运行记录与结果，并进行同批对账。当前没有B的作业或统计结果；本文件不代表已通知B。

## 查询接入

`backend.app.repositories.attractions.AttractionRepository`接收无参数据库连接工厂，提供批次、列表、详情、统计和完整推荐候选读取。调用者负责提供只读连接与UTC会话。只有明确指定的ready批次可读，当前真实批次仍是loading。

`backend.app.repositories.error_adapter.RepositoryAdapter`可接收C实现的`AppError`类及数据库连接异常类型。C负责公共错误类型和HTTP映射；当前适配器仅用替身及独立测试库验证，尚未与Flask或C的模块联调。候选迭代器应完整消费或显式关闭；SQL中途失败应终止整次推荐。

本机`tourism_reader`仅允许Linux用户通过本地Unix socket读取项目库，不是可跨机器复用的账户；部署时应按环境约定建立只读账号，切勿把凭据写入仓库。构造MySQL验证库与真实loading批次相互独立。

## 当前交付限制

- Python 3.11数据依赖、查询及保护测试已在本机运行；其他角色依赖组尚待相应角色验证。
- 尚无已导入的真实Spark/MapReduce统计或已发布ready批次；数据库查询、分析、网页尚未完成端到端联调。
- 已有代码与该说明当前为本地改动；同步远端和公开数据必须按项目Git及来源使用边界处理。

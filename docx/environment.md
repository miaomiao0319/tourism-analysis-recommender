# 环境、运行与部署约定

- 文档状态：已验收基线；实现与运行状态见 milestones.md。
- 主要读者：负责环境准备、数据处理、计算和网站运行的 A/B/C agent。
- 依据：[项目要求](project.md)、[系统架构](architecture.md)、[角色分工](roles.md)、[数据契约](data-contract.md)、[接口契约](api-contract.md)。

用户只说“我完成 A/B/C 的任务”时，agent 按角色准备所需环境、执行检查并记录结果，不要求成员本人先阅读文档、填写环境表或逐条执行命令。先检查现有安装、仓库和当前阶段，不覆盖已有工作，不因本文提供安装方案就跳过文档准备阶段。

**修改、删除、重命名或移动本文件，必须事先获得人工对具体变更的明确批准。** 软件基线、运行模式和任务归属已经验收，实际安装、计算与部署仍待实施验证。当前阶段以用户最新指示及 milestones.md 为准；下文规划的程序与入口须实现后才能运行，不能因规范已验收就跳过阶段限制。

## 1. 统一运行方案与任务归属

采用 Linux 单机方案：Windows 成员使用 **WSL2 + Ubuntu 24.04 LTS**；原生 Ubuntu 24.04 可直接执行 Linux 步骤。离线计算使用单机伪分布式 HDFS/YARN，网站使用 MySQL、Flask、Vue/ECharts。Spark SQL 使用 `local[2]` 读取同一 HDFS 输入，不额外搭建 Spark 集群。

项目最小部署是能在浏览器实际使用的本机网页系统；集成演示时将 Vue 构建结果交给 Flask，通过一个网页地址提供服务。公网服务器、域名和付费资源未确定，不自行购买或承诺公网访问。Docker、独立虚拟机、多节点集群不属于本方案的必装项；确需替换运行方案时，先提出具体变更供人工批准。

本文件补全此前明确留待环境阶段决定的任务：

| 负责人 | 环境阶段新增或细化的职责 | 应交付的可复现入口与证据 |
| --- | --- | --- |
| A | Linux 下 Java 11、Hadoop/HDFS/YARN 的安装配置与启停；HDFS 标准批次上传和完整性检查；MySQL 安装、建库、导入与恢复；采集清洗环境。 | Hadoop 配置生成与启停入口、HDFS 上传入口、数据库入口、实际版本与输入校验记录。 |
| B | `analysis/mapreduce/` 中项目 MapReduce 作业与结果转换；Spark SQL 环境和作业；两者同批次对账。 | MapReduce/Spark 运行入口、作业标识、统计输出及对账记录；不能将 Hadoop 服务安装也全部转交给 B。 |
| C | Node/npm、Vue/ECharts、Flask/WSGI 环境；网页开发、构建与部署接入；组织全流程启动检查。 | 网页启动入口、Vite 代理配置、Flask 应用入口、构建产物接入及实际网页验证。 |

每位 agent 负责复现自己角色需要的环境。A 交付的 Hadoop 配置和脚本供 B 直接复用，B 不再维护一套冲突的集群配置；C 不因负责集成而接管 A/B 的缺失实现。集成机器可以同时承担全部运行角色，责任归属不随机器归属变化。

以上分配已获确认，并按 2026-10-21 统一整理授权同步到 `roles.md` 及相关引用；原有 35%/35%/30% 保留为工作量估计，不声称已重新测算占比。后续如需改变分工或运行方案，先指出具体影响并取得相应批准，不擅自改写受保护文档。

## 2. 软件基线与版本锁定

以下是项目选择的兼容基线，不代表本机已经安装或验证通过；官方依据见各行链接。软件补丁版本及完整依赖在首次环境实现时解析、检查并锁定，后续成员复用仓库中的锁定结果。

| 组件 | 统一基线 | 安装与兼容要求 |
| --- | --- | --- |
| 系统 | Ubuntu 24.04 LTS，64 位；Windows 经 WSL2 运行 | Linux 命令在 Ubuntu 中执行，不能把 PowerShell 当 Bash。WSL 安装和发行版检查遵循 [Microsoft 官方说明](https://learn.microsoft.com/en-us/windows/wsl/install)。 |
| Java | OpenJDK 11，包含 JDK | Hadoop 3.4 使用 Java 11 运行；不从源码编译 Hadoop。项目进程显式使用 Linux JDK 11，不能借用 Windows 的 Java 或默认切到 17/21。[Hadoop Java 支持说明](https://cwiki.apache.org/confluence/spaces/HADOOP/pages/100827883/Hadoop%2BJava%2BVersions)、[Ubuntu JDK 11 软件包](https://packages.ubuntu.com/noble/openjdk-11-jdk)。 |
| Hadoop | **3.4.3**，官方二进制包 | HDFS 与 YARN 同一发行包；单机伪分布式，不使用本地模式冒充实际 YARN 作业。[单机配置说明](https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/SingleCluster.html)。 |
| Python | CPython **3.11.x** | 用 uv 管理项目 Python 与虚拟环境，保留系统 Python；首次解析 3.11 的可用维护版本并将完整版本写入 `.python-version`。[uv Python 管理](https://docs.astral.sh/uv/guides/install-python/)。 |
| Spark / PySpark | **3.5.8**，PyPI 的 Hadoop 3 发行形式 | `pyspark==3.5.8`，复用 Java 11 和项目 Python。仅通过这一安装方式提供 Spark，不同时再安装另一版 Spark 或混用其 JAR。[Spark 3.5.8 运行要求](https://spark.apache.org/docs/3.5.8/)、[PySpark 安装说明](https://spark.apache.org/docs/3.5.8/api/python/getting_started/install.html)。 |
| MySQL | **8.4 LTS** | 使用官方 8.4 LTS 软件源，锁定实际安装的软件包版本；不使用 Ubuntu 默认包来推断一定得到 8.4，也不用 MariaDB 替代。[官方 APT 安装说明](https://dev.mysql.com/doc/refman/8.4/en/linux-installation-apt-repo.html)。 |
| Node.js | **22.23.3** | Linux 内安装该完整版本，使用随附 npm，并记录 `npm --version`；不调用挂载路径中的 Windows node/npm。[官方版本档案](https://nodejs.org/en/download/archive/v22)。 |
| 页面依赖 | Vue **3.x**、Vite **7.x**、ECharts **6.x** | 首次解析后由 package-lock.json 固定完整版本。Node 基线满足 Vite 7 的要求；不使用无版本的最新脚手架自动升级到其他 Vite 主版本。[Vite 7 要求](https://v7.vite.dev/guide/)、[ECharts 6 说明](https://echarts.apache.org/handbook/en/basics/release-note/v6-upgrade-guide/)。 |
| Python 业务依赖 | Scrapy **2.x**、Pandas **2.x**、Flask **3.1.x** | 在 Python 3.11 下解析并锁定可用版本；数据库连接采用 PyMySQL 1.x 及其 RSA 认证依赖，配置读取采用 python-dotenv，网页演示采用 Gunicorn。具体修补版本和传递依赖以 uv.lock 为准。[Scrapy 安装](https://docs.scrapy.org/en/latest/intro/install.html)、[Flask 要求](https://flask.palletsprojects.com/en/stable/installation/)。 |

基线内首次解析与普通锁文件维护属于实现工作，不等于修改本文件；改变上述版本系列、Hadoop/Spark 固定版本、运行方式或依赖管理方式仍须人工批准。不能为让安装通过而悄悄删除必用组件或退到另一套版本。查到兼容范围只能记为“官方范围已核对”，必须实际检查后才能记为“环境验证通过”。

### 2.1 依赖文件与维护边界

| 文件或产物 | 约定 |
| --- | --- |
| 根目录 `pyproject.toml`、`uv.lock`、`.python-version` | 一套 Python 环境与锁文件。A 首次建立，A/B/C 只添加职责所需依赖并同步解析锁文件；不能为每个模块复制另一套 Python 版本。 |
| Python 依赖分组 | 公共依赖放项目 dependencies；`data` 放 Scrapy/Pandas，`analysis` 放 PySpark，`web` 放 Flask/Gunicorn，`dev` 放必要检查工具。共享使用的包只声明一次；推荐模块不强制依赖 Flask 或 Spark。 |
| `frontend/package.json`、`frontend/package-lock.json`、根目录 `.nvmrc` | C 首次建立，.nvmrc 写 22.23.3；前端完整依赖和包管理器版本由锁文件及 package.json 记录。已有锁后使用 npm ci。 |
| `scripts/environment-versions.json` | A 首次建立的机器可读安装记录，C 补充 Node/npm 信息；保存 uv、JDK、MySQL 的实际完整版本、对应架构、安装来源和下载包校验和，供其他 agent 直接复现。不记录密码、用户名或个人路径，不另写一份环境规范。 |
| `.env.example` | 已建立的受保护公共配置说明，只放变量名、非敏感示例与必要生成说明。修改其共享约定需人工批准。 |
| `.env`、`.venv/`、`.runtime/`、node_modules、dist | 本机配置、环境或生成结果，不提交仓库；由 .gitignore 排除。忽略规则不会自动清除已跟踪内容，提交前仍须检查。 |

不维护一份与 uv.lock 独立漂移的 requirements 清单。对接确需 requirements 时，从锁文件生成并标注生成方式。已有锁文件的安装使用 `--locked`，失败时先排查，不能自动重锁。未被应用依赖锁覆盖的安装版本写入上述共享版本记录，接手 agent 对照复现，不重新挑选最新补丁；首次尚无记录时明确说明尚未锁定，不编造版本号。基线内的维护更新随代码 PR 修改该记录并重新验证；更改记录不能绕过本文件的基线保护。

## 3. 工作目录、资源与配置

### 3.1 工作目录与资源

一个 agent 会话只使用当前选定的有效 checkout。现有 Windows 仓库不因本文自动迁移。进入实现阶段、文档合并后，可在 WSL Linux 文件系统重新克隆已发布仓库，并将开发会话切到该 checkout；迁移前检查未提交文件，不能遗失或覆盖现有内容，也不能维护两份靠手工复制同步的活动副本。Linux 工具在 Linux 文件系统工作可减少跨系统文件访问开销，参见 [WSL 文件存储说明](https://learn.microsoft.com/en-us/windows/wsl/filesystems)。

Linux 命令中的 `PROJECT_ROOT` 是 agent 从当前 checkout 解析的绝对路径，不是成员手工填写的固定用户名目录。路径始终加引号；共享源码不写个人桌面绝对路径。代码与标准交换文件用 UTF-8、LF；CSV/JSONL 的细节仍以数据契约为准。

完整计算环境建议为 Linux 分配约 4 个逻辑 CPU、8 GiB 内存，并预留约 30 GiB 可用磁盘；这是首次小样本运行的规划参考，不是课程硬指标或已测出的最低配置。agent 先检查实际资源，计算串行执行，Spark 默认 local[2]、driver memory 2g；不默认并行运行两个计算引擎。容量随数据与备份增长，不能用低资源为由删除必用环节。

A 的日常工作需要 data 依赖、MySQL 和 HDFS；B 需要 analysis 依赖、Java/Hadoop 客户端，并能访问同机 HDFS/YARN；C 开发网页需要 web 依赖、Node 和可用的同批 MySQL 数据，不要求一直运行大数据服务。全流程验证机器安装全部角色依赖，验证职责仍由对应角色承担。

### 3.2 环境变量及端口

本机根目录 `.env` 使用 dotenv 键值格式。Python 配置模块由 C 组织，A/B 复用，不各写一套默认值；离线入口在没有网站代码时也应能独立加载所需配置。进程环境变量优先于 .env。Shell 不直接 `source .env` 或 `eval` 其内容；.env 内的 `${变量}`、`~` 和命令文本不作为自动路径生成约定。

| 变量 | 默认值或生成方式 | 使用方 |
| --- | --- | --- |
| `PROJECT_ROOT` | 从实际 checkout 解析，由入口生成，不依赖 .env 手填 | 全部 |
| `JAVA_HOME` | 当前 Linux JDK 11 的真实安装目录，A 从软件包定位并验证 | A/B |
| `HADOOP_HOME` | agent 实际解压 Hadoop 3.4.3 的目录，可在 `.runtime/tools/` 下 | A/B |
| `HADOOP_CONF_DIR` | 由 A 从配置生成入口产生，默认 `.runtime/hadoop/conf/` 的绝对路径 | A/B |
| `HDFS_URI` | `hdfs://localhost:9000` | A/B |
| `HDFS_ROOT` | `/tourism`，项目专用 HDFS 根路径 | A/B |
| `PYSPARK_PYTHON`、`PYSPARK_DRIVER_PYTHON` | 指向同一 checkout 的 `.venv/bin/python` 绝对路径，由入口生成 | B |
| `SPARK_MASTER` | `local[2]` | B |
| `DB_HOST`、`DB_PORT`、`DB_NAME` | `127.0.0.1`、`3306`、`tourism_recommender` | A/C |
| `DB_USER`、`DB_PASSWORD` | 本机最小读取权限账号及实际密码；没有可用默认密码 | 在线服务 |
| `DB_IMPORT_USER`、`DB_IMPORT_PASSWORD` | 本机导入账号及实际密码，仅导入进程读取 | A |
| `ACTIVE_BATCH_ID` | A/C 交接并校验的明确 ready 批次；空值表示未就绪 | 在线服务 |
| `FLASK_HOST`、`FLASK_PORT` | `127.0.0.1`、`5000`；入口显式读取，不能假定 Flask 自动识别本项目变量 | C |
| `VITE_API_BASE_URL` | `/api/v1`，公开构建配置，不能放任何秘密 | C |
| `VITE_DEV_PROXY_TARGET` | `http://127.0.0.1:5000`，开发代理目标 | C |

相对文件路径统一以 PROJECT_ROOT 解析后使用；HDFS_ROOT 是 HDFS 路径，不能按本地路径拼接。Hadoop 守护进程不自行读取 .env，A 的入口需校验配置并生成 XML、hadoop-env.sh；PySpark 入口显式传递 Java、Hadoop 配置与 Python 环境。不能只在 .env 写变量就声称组件已使用。

前端开发地址固定为 `http://127.0.0.1:5173`，Vite 使用 strictPort，端口占用即提示原因，不自动换端口。前端请求相对 `/api/v1`，开发由 Vite 代理到 5000，构建演示由 Flask 同源处理；浏览器中不默认另开跨域请求，Flask 不启用通配 CORS。Vite 显式从项目根配置读取所需公开变量及代理目标，不能把整个根 .env 注入页面。

其他默认端口：HDFS RPC 9000、NameNode 页面 9870、YARN 页面 8088；其余 Hadoop 端口由配置入口记录。开发服务默认本机访问，MySQL/Hadoop/YARN 不暴露到公网。网页需局域网演示时，可通过本机配置调整网页监听地址并验证实际地址；不顺带开放数据库或计算服务。

真实凭证不进入 Git、日志、命令行参数或网页构建变量。MySQL 建库使用有相应权限的本机管理身份，在线进程不使用 root 或导入账号；认证依赖通过 PyMySQL 的 RSA extra 安装，不通过关闭密码认证或降级旧认证插件规避错误。

## 4. agent 创建环境的顺序

这些步骤在进入环境实现任务后执行。agent 先读现有文件与锁，复用已符合基线的安装。缺少本角色入口时完成最小实现；缺少其他角色交付时记录依赖，并继续可独立工作，不能以空脚本冒充就绪。

### 4.1 检查和准备 Linux

Windows 先执行只读检查，确认发行版实际运行于 WSL2：

```powershell
wsl --status
wsl --list --verbose
```

仅在缺少目标发行版且已进入环境准备任务时，按官方方式安装 `wsl --install -d Ubuntu-24.04`。这可能要求管理员权限、重启和首次账号初始化。agent 先完成可自动完成的检查，仅在系统确实要求时说明具体原因并请求最小人工操作，不要求用户按文档手工重做全部安装。E_ACCESSDENIED 不能据此判断 WSL 一定未安装。

Ubuntu 中的基础依赖可由环境 agent 安装；web-only 开发无需为此额外安装 Hadoop：

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates unzip openjdk-11-jdk
```

uv 按[官方安装方式](https://docs.astral.sh/uv/getting-started/installation/)安装到用户环境，记录版本；Python 由 uv 管理的构建提供，不替换系统 python3。Hadoop 与 Node 下载固定版本、对应 Linux 架构的官方包，并验证官方校验和；MySQL 按官方 APT 说明明确选择 8.4 LTS。下载不可用时记录实际失败，不改用不明二进制包或无版本 latest。

### 4.2 首次锁定与后续复现

首次由 A 建立根 pyproject、依赖分组与锁文件，协调 B/C 提供本模块必要依赖；C 建立前端依赖文件。首次 Python 完整版本的生成步骤如下，须在实际 checkout 根目录执行；已有 .python-version 时不能覆盖：

```bash
uv python install 3.11
uv venv --python 3.11
.venv/bin/python --version
```

A 从该解释器读取实际 `3.11.N` 并用 `uv python pin` 将完整版本写入 .python-version，再解析依赖、生成 uv.lock、运行本角色检查。后续成员直接使用已提交的精确版本文件，不重新选择一个更新的 3.11 补丁。

锁文件和声明已建立后，日常复现从 checkout 根目录运行对应分组；以下三行是三种角色用法，不要求顺序全部执行：

```bash
uv sync --locked --group data --group dev
uv sync --locked --group analysis --group dev
uv sync --locked --group web --group dev
```

uv 同步会移除未选分组依赖；同一机器兼任角色时，在一次 sync 中列出所有需要的分组。完整集成环境使用 `uv sync --locked --all-groups`。运行入口使用已同步的 `.venv/bin/python` 和 `.venv/bin/` 下命令，不在运行时隐式重解析依赖。B 设置 PYSPARK_PYTHON 与 driver Python 指向该解释器。

前端已有 package-lock.json、Node/npm 基线符合时，在 frontend 执行 `npm ci`。首次由 C 根据本文系列声明并锁定依赖，不使用“已有 package.json、缺锁却执行 npm ci”的假步骤。代理或镜像只改变获取位置，不能静默改变版本、跳过证书验证或提交凭证。

## 5. HDFS、YARN 与 MapReduce 的实际运行

### 5.1 配置和服务生命周期：A

A 在 `scripts/` 实现 `hadoop.sh init|start|status|stop`，配置生成逻辑随该入口维护，不新建另一份人工环境配置文档。模板中保留变量，由入口生成本机实际路径；启动前检查 JDK 11、端口与目录权限。

| 配置 | 项目要求 |
| --- | --- |
| core-site.xml | fs.defaultFS 与 HDFS_URI 一致；hadoop.tmp.dir 使用 `.runtime/hadoop/` 内明确的绝对目录。 |
| hdfs-site.xml | dfs.replication=1；NameNode 元数据与 DataNode 数据使用 `.runtime/hadoop/` 下不同持久目录，不能放入会在普通清理中删除的临时目录。 |
| mapred-site.xml | mapreduce.framework.name=yarn，按本发行版配置 MapReduce 应用 classpath。 |
| yarn-site.xml | 启用 mapreduce_shuffle，配置本机 ResourceManager 和必需环境白名单；按实际可用资源设置容器和调度内存，不只增加 JVM heap。 |
| hadoop-env.sh 与进程配置 | 显式使用 Linux JAVA_HOME；设置本项目日志/PID 目录及适当堆上限，不改系统全局 Java 默认版本。 |

init 仅用于确认是本项目、尚无已有元数据和数据的全新目录；先显示解析后的目标，验证全部目录位于本项目运行区，再进行首次 NameNode 初始化。发现 VERSION、已有数据、不可解释的部分初始化或路径越界即停止并排查。普通 start、重试和恢复绝不能自动 format，也不能删除数据目录“修复”错误。

单机入口用 `hdfs --daemon`、`yarn --daemon` 在本机管理 NameNode、DataNode、SecondaryNameNode、ResourceManager、NodeManager，不依赖免密 SSH；如果实现改用官方 start-dfs/start-yarn 脚本，需同时满足其 SSH 前提，不能交付只能在维护者机器运行的隐藏配置。SecondaryNameNode 负责检查点，不是 NameNode 高可用备机。

status 检查进程与实际服务，不只看 jps 名单：至少检查 `hdfs dfsadmin -report` 中可用 DataNode、`hdfs dfs -ls /`、`yarn node -list` 中可用 NodeManager，以及一次独立测试文件写入、读回、比对与清理。测试文件使用独立命名，不能占用真实批次路径。单机复制因子 1 不提供容错副本，不将该环境描述成多机器性能或高可用验证。

### 5.2 批次入湖：A

输入从数据契约的标准 CSV 与配套元数据产生，HDFS 目录统一为：

```text
/tourism/batches/<batch_id>/input/attractions.csv
/tourism/batches/<batch_id>/metadata/manifest.json
/tourism/batches/<batch_id>/metadata/dictionaries.json
/tourism/batches/<batch_id>/runs/<run_id>/mapreduce/
/tourism/batches/<batch_id>/runs/<run_id>/spark_sql/
```

HDFS_ROOT 改为其他项目专用根时，相对层级保持一致。source/evidence 元数据按数据契约留存和交接，不把含原始页面的目录当作标准计算输入。

A 实现 `scripts/upload-hdfs.sh --batch-id <id>`：先验证本地 manifest、CSV SHA-256、字典 SHA-256、数量和引用，再将完整 input 与 metadata 上传到 HDFS_ROOT 下独立 staging 目录；读回比较相同字节的 SHA-256 后，整体重命名为正式 batches/batch_id 目录，不逐个暴露半批文件。失败的 staging 不算可用输入。正式批次路径已存在时只核对一致性，一致则幂等成功，不一致报错，不使用覆盖参数改写同一个批次。

HDFS 自身 checksum 不等于文件内容 SHA-256，不能将两者字符串直接比较。批次内容或字典改变必须使用新 batch_id；run_id 只区分同一不可变输入的不同运行尝试，不能成为偷偷修改输入的手段。run_id 沿用 batch_id 的 1—64 位 ASCII 字母、数字、下划线或连字符限制；所有入口先校验标识再拼接路径或调用命令。B 启动作业前确认正式目录及 manifest、输入和字典摘要有效，不读取 staging。

### 5.3 MapReduce：B

最小实现采用 **Hadoop Streaming + Python mapper/reducer**，在真实 YARN 上执行城市与等级计数。Streaming 使用 Hadoop MapReduce 的任务、shuffle 和 reducer，不是用 Python 单进程计算后贴上 MapReduce 标签，参见[官方 Streaming 说明](https://hadoop.apache.org/docs/r3.4.3/hadoop-streaming/HadoopStreaming.html)。不要求另写 Java 业务代码或引入 Maven。

B 实现 `scripts/run-mapreduce.sh --batch-id <id> --run-id <id>`，调用 Hadoop 3.4.3 自带的 streaming JAR，通过 -files 分发 mapper/reducer 等必要代码。单机 YARN 的任务显式调用同一项目虚拟环境 Python 的绝对路径，mapper/reducer 优先只用 csv/json 等标准库，不能依赖任务进程碰巧继承开发终端的 PATH。

- 输入只指向该批次的 attractions.csv；不能递归读取整个批次目录，把 manifest 或输出也算进去。
- CSV 用正确解析器处理，21 列顺序、JSON 字段、UTF-8 与一条记录一物理行遵守数据契约；不能 split(',')。准确识别并跳过规范表头一次，不按名称模糊跳过普通记录。
- mapper 按城市、等级的契约维度输出可区分的键；reducer 计数，可用一个作业产生两类结果。未知城市、未知/冲突等级保留，不能丢弃。
- 设置非零 reducer，必须实际通过 YARN 执行；不能接受 LocalJobRunner 结果冒充。异常输入使作业失败或按已批准策略明确隔离，不能无提示少算。
- 每次使用新的 runs/run_id 输出目录；Hadoop 要求目标输出目录事先不存在，重跑不删除旧证据来凑成功。
- 保留 YARN application_id、作业完成状态、输入路径、记录数、计数器、运行命令与日志。项目真实数据的作业结果才证明必用环节完成，官方 WordCount/Pi 成功只算环境冒烟检查。

## 6. Spark SQL 与结果交付：B

B 实现 `scripts/run-spark.sh --batch-id <id> --run-id <id>`，使用 `.venv/bin/spark-submit`、明确的 `--master 'local[2]'` 和所需 Python 环境，从与 MapReduce 相同的 HDFS CSV 读取。显式声明契约字段类型、CSV 引号/转义规则与表头，金额采用 Decimal 类型；不能用 inferSchema 把标识改成数值或用浮点计算价格。

Spark 复用 HADOOP_CONF_DIR 与 HDFS_URI；保留 PySpark 自带的 Hadoop 客户端，不将 HADOOP_HOME 下所有 JAR 加入 Spark classpath。该组合是否能正确读写以实际 HDFS 样本验证为准，不凭“都是 Hadoop 3”跳过检查。最小 SQL 统计不引入 Arrow、Spark Connect 或常驻 Spark 服务。

两个引擎原始输出分别留在对应 HDFS run 目录。B 校验后转换为数据契约的 `data/results/<batch_id>/<engine>/statistics.jsonl` 和 `run.json`；JSONL 是已计算结果的序列化，不能在转换时由 Pandas 或另一引擎重新计算后冒称原引擎结果。

本地每个批次、每个引擎只有一份待交付的已选运行结果，run.json 指向实际 run_id 及原始输出；重复尝试保留原始证据，不将不同尝试的半成品拼成一次成功。两引擎对 city/grade 分组逐项核对，包括 null 分组、维度和数量；验证通过后才交给 A 导入。对外统计读取 Spark，MapReduce 用作独立对账，不能累加两者。

先以契约构造样本验证边界，再用真实采集小样本跑通。构造数据始终 data_kind=test，不代表实际数据成果；价格政策为空时输出 pending_policy 只是诚实表达未就绪，不能因此记为真实价格分析和预算功能已验收。

## 7. MySQL、批次发布与恢复：A/C

A 初始化 `tourism_recommender` 数据库并实现数据契约的四张逻辑表；使用 utf8mb4，ID 与维度键精确区分大小写，名称搜索采用明确的一致比较规则。连接会话使用 UTC，时间与金额转换遵守数据契约。初始化可重复执行，不默认 DROP、TRUNCATE 或改写已有 ready 数据。

建议运行入口由 A 在 `scripts/` 提供：

| 入口 | 行为 |
| --- | --- |
| `init-db.sh` | 检查目标实例与库，创建必要结构及本地账号授权步骤；管理权限只用于必要初始化，不写入在线配置。 |
| `import-batch.sh --batch-id <id>` | 校验标准数据、字典、来源证据、两引擎运行与对账结果；按 loading → ready/failed 管理导入，不擅自启动网站或挑选最新批次。 |

上述为入口交付约定，不表示当前已经存在脚本。导入与查询可调用 processing/database 内实际模块，Shell 只组织调用，不复制清洗或统计逻辑。price policy 缺失等已声明功能限制需同时交接；数据可服务不等于全项目验收通过。

发布新批次时，C 暂停 Flask/WSGI 服务，A 保留上一有效批次及可恢复备份，完成新批次导入、数量/引用/统计检查后，由 C 明确将 ACTIVE_BATCH_ID 配置为该 ready 批次再启动服务。不能只更新景点而保留旧统计，也不能由各接口分别查询最大时间戳。

启动后的 dataset 返回实际批次；前端按接口契约保存并携带 batch_id。导入失败保持服务暂停，A 恢复已验证状态，C 恢复原 ACTIVE_BATCH_ID 并重新验证后再启动。首次尚无可用批次时，health 可响应，数据接口返回契约的未就绪错误，不填入演示常量。

备份和恢复材料留在本机受控位置，包含所需数据库数据和元数据，不依赖重新爬取恢复。日常检查、环境重建和停止计算服务均不能删除数据库、HDFS 持久目录或上一有效批次。

## 8. 网页启动与演示部署：C

C 实现 Flask 工厂入口 `backend.app:create_app`，加载根配置并接入 A 的查询与 B 的推荐函数；从 checkout 根目录启动。前端实现 npm scripts `dev` 和 `build`，不因脚本尚未创建而把下列命令记为已可运行。

开发模式：先启动 MySQL，再从根目录运行接口；同时在 frontend 中运行 Vite。

```bash
.venv/bin/flask --app backend.app:create_app run --host 127.0.0.1 --port 5000
```

```bash
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

以上展示默认监听值。读取环境变量的实际启动入口由 C 实现，不能让 FLASK_HOST/FLASK_PORT 配置与命令长期不一致；不默认开启 debug 或自动重载。开发浏览器地址为 http://127.0.0.1:5173，经代理访问同源 API。

集成演示：在 frontend 执行 `npm ci`、`npm run build`，C 将生成的 `frontend/dist` 交给 Flask；从根目录用 Linux Gunicorn 启动：

```bash
.venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5000 'backend.app:create_app()'
```

浏览器访问 http://127.0.0.1:5000。WSGI 使用实际配置的监听值，上面是默认示例；一 worker 是本机演示起点，不是性能验收结论。Flask 内置开发服务器和 vite preview 不作为正式网页部署服务；WSGI 选择依据见 [Flask Gunicorn 部署说明](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)。

Flask 提供真实静态资源和前端路由回退，但 `/api/v1` 下的未知路径与错误必须保持统一 JSON，不能回退到 index.html；不存在的静态资源也不能伪装成成功页面。地图资源与页面依赖按许可及项目公开分发方案处理，不能让关键演示依赖维护者电脑缓存或一个未说明的外部资源地址。

网站运行时只需要 MySQL、Gunicorn 和已构建页面，查询与推荐不启动离线作业。计算完成且结果发布后可正常停止 Hadoop/YARN；演示计算过程时再由 A 启动、B 运行项目作业。关闭计算服务不影响已经正确导入的网页数据。

## 9. agent 实际检查与交接

agent 自动收集和解释检查结果，不能仅把下面的清单转交给成员手工执行。

| 层次 | 责任与通过依据 |
| --- | --- |
| 版本与路径 | 各角色检查实际 OS/架构、java/uv/Python/Hadoop/PySpark/MySQL/Node/npm 版本及解析路径；不混用 Windows 可执行文件，不把“命令存在”视为服务成功。 |
| 数据与计算 | A 验证标准 CSV 与 HDFS 字节一致；B 确认 YARN 作业完成、Spark 实际读 HDFS，构造样本计数和真实小样本对账正确。 |
| 数据库 | A 校验批次状态、四表关联、数量、大小写标识与价格精度；测试失败导入不发布半批数据，重复导入不增加重复记录。 |
| 接口与推荐 | A/B/C 按接口契约验证查询、同批统计、完整候选推荐、预算零值、未知价格、无匹配和错误反馈。 |
| 页面与恢复 | C 验证构建后可从单一地址访问，筛选/地图/推荐实际变化，test 标记与来源说明可见；A/C 验证新批次切换、失败恢复和重启后仍读正确批次。 |

每个角色 agent 将实际环境信息、运行入口、批次、证据位置、通过项目和未通过事项交接给接收方；日常进度只更新 milestones.md，不回写本规范。环境与运行记录可放入本机 `.runtime/` 及数据契约的 run.json；需共享时剔除密钥和私人路径，遵守数据再分发限制。依赖锁文件、必要源码和可公开配置模板随代码交付，不提交虚拟环境或全部运行数据。

常见问题按证据定位：Java/Python 路径错先修入口配置；HDFS 不可用由 A 检查服务与持久目录；YARN 容器失败由 B 检查作业日志并与 A 核对资源配置；Spark 类冲突先排除重复 JAR；MySQL 认证检查账号权限和驱动依赖；端口冲突先识别占用进程，不擅自终止其他项目。不能自动 format、删库、跳过校验、取消预算或返回假数据来掩盖失败。

当前仅完成官方资料与既有契约的核对，尚未验证本项目安装、计算、数据库或网页运行。首次实际环境通过后，由 agent 记录真实结果；若基线无法支持必需功能，提出具体原因、替代方案和需修改的受保护条目，获得人工批准后再调整。

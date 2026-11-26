# 山河图鉴 · 偏好推荐

## 先看页面

交付包中的 `Shanhe_Atlas.html` 可以直接下载，用新版 Edge、Chrome、Firefox 或 Safari 打开。离线版提供 6 个预设预算和“不限预算”。每种地区、兴趣、排序和预算组合的结果都来自演示服务调用 B 的推荐模块后保存的响应。它使用 3 条构造样本，页面顶部标有“演示样本”。

## 在电脑上启动 Flask 演示

项目使用 Python 3.11.18、Node 22.23.3。以下命令从仓库根目录在 Linux 或 WSL 执行。解压交付包后已有 `frontend/dist`，可直接跳过两条 npm 命令。

```bash
uv sync --locked --group web --group dev
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m scripts.web --demo
```

浏览器打开 <http://127.0.0.1:5000>。此模式可以自由输入金额；保留两位小数。选“全部地区”“不限兴趣”，输入 70、60、0 元，演示样本依次匹配 2、1、0 条。清除预算，选“人文古迹”可以查看票价未知的构造景点。点击“景点详情与来源”查看票种和资料出处。

修改前端时，另开终端从根目录运行 `npm --prefix frontend run dev`，打开 <http://127.0.0.1:5173>。开发服务器将 API 请求转给 Flask。页面横幅为本项目生成的山景氛围图。

## 接 A 的真实数据

在可访问项目 MySQL 的机器上按根目录 `.env.example` 填写本机 `.env`。设置 DB_HOST、DB_PORT、DB_NAME、DB_USER、DB_PASSWORD 和 ACTIVE_BATCH_ID。若使用 A 的本机 Unix socket 账号，可像 A 的导入程序一样设置 DB_UNIX_SOCKET，并在有权限的系统用户下运行。使用 A 已校验的只读账号，数据库密码留在本机。

A 的交接批次为 `atlas_clean_20261102_02`。在目标机确认批次仍为 ready 后运行下列命令。

```bash
.venv/bin/python -m scripts.web
```

默认浏览器地址为 <http://127.0.0.1:5000>。服务从当前配置读取主机和端口。需要用 WSGI 演示时，可使用项目约定的 Gunicorn 入口，例如 `.venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5000 'backend.app:create_app()'`。

先看“数据说明”中的真实批次 ID 和数据量，再验证 70 元和 0 元的返回值。若未连接数据库或未配置 ready 批次，页面会提示原因并提供“重新连接”。

## 修改入口

| 内容 | 文件 |
| --- | --- |
| 页面布局、筛选状态、结果卡与详情弹窗 | `frontend/src/App.vue` |
| 桌面与手机样式 | `frontend/src/style.css` |
| 网络请求 | `frontend/src/transport.js` |
| Flask 应用、只读连接、错误映射 | `backend/app/web_app.py` |
| health、dataset、recommendations、景点详情 | `backend/app/routes/recommendations.py` |
| 独立演示样本 | `scripts/web_sample.py` |

从根目录运行 `.venv/bin/python -m unittest discover -s tests -p test_web_recommendations.py` 验证接口。需要重新导出独立 HTML 时，先安装前端依赖，再运行 `.venv/bin/python -m scripts.build_web_preview .runtime/Shanhe_Atlas.html`。

## 景点查询与统计展示

本版“景点查询”调用 `GET /api/v1/attractions`，支持名称子串、地区、等级、类型、门票上限、排序和服务端分页。点击记录读取详情与来源。“景点分布”调用 `GET /api/v1/statistics`，逐页取得同批 Spark SQL 分组，展示省级分布、城市数量前十、等级，以及所选票价口径的样本数与分布。无统计、未知地区、无可比价格和真实零值分别展示。地图点击有记录的省份可进入查询页，筛选会带上该省份。

地图使用本地的 Natural Earth Admin 1（1:50m，natural-earth-vector v5.1.2）。`frontend/src/assets/provinces.json` 选取本项目覆盖的 31 个省级地区、保留名称和简化精度的坐标。通过当前批次地区字典的中文省名匹配；无法匹配的分组另列。地图仅表示本数据集的统计覆盖范围。来源与使用条款：[源文件](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_50m_admin_1_states_provinces.geojson)、[公共领域条款](https://www.naturalearthdata.com/about/terms-of-use/)。

六个接口可在 A 运行网站的机器上一键核对。将批次参数替换成 A 当前选定的 ready 批次，执行：

```bash
.venv/bin/python -m scripts.verify_web --expected-batch atlas_clean_20261102_02
```

仅在本机演示新页面时可运行 `.venv/bin/python -m scripts.web --demo`。若要用 Gunicorn 验证同源构建和重启，可在测试目录运行 `.venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5000 'scripts.web:create_demo_app()'`，其批次为 test_c_travel_guide。正式部署入口仍为 `backend.app:create_app()`。

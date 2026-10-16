# 鳄鱼文库 · Gator Library

「鳄鱼派投资档案」（https://gator.ronchy2000.top/ ）的全量个人镜像：
爬取全部 **每日信息 / 每日复盘 / 历史研报 / 投资随笔**，按类别归档，生成一套
**暗黑 / 浅色双主题（朱砂红点缀）** 的纯静态阅读站，支持全文搜索。
图片可一键上传到自己的文件服务器。

```
总计 1636 篇：每日信息 98 · 每日复盘 622 · 历史研报 913（宏观 238 / 行业 638 / 其他 37）· 随笔 2
（以实际爬取结果为准）
```

## 目录结构

```
gator-reader/
├── crawler/crawl.py          # 爬虫（可断点续爬，礼貌限速）
├── data/
│   ├── items/*.json          # 每篇内容：元数据 + 清洗后的正文（data/ 目录较大，属于资产）
│   └── images/<slug>/*.png   # 文章图片本地镜像
├── generator/
│   ├── build.py              # 静态站生成器（纯标准库）
│   └── assets/               # style.css / app.js / favicon.svg 源文件
├── site/                     # 生成产物（直接部署这个目录）
├── upload/
│   ├── config.example.json   # 文件服务器配置模板
│   └── upload_images.py      # 图片上传工具（webdav / http / s3）
├── site.config.json          # 站点配置（站名、图片基址、免责声明）
└── README.md
```

## 快速开始

```bash
# 1. 本地预览（site/ 已生成好，可直接看）
cd site && python -m http.server 8390
# 打开 http://127.0.0.1:8390/

# 2. 增量更新：重跑爬虫（已爬过的自动跳过）→ 重新构建
python crawler/crawl.py
python generator/build.py
```

## 图片上传到自己的文件服务器

1. 复制配置模板并填写：

```bash
cp upload/config.example.json upload/config.json
```

2. 按你的服务器类型改 `config.json`：

| type | 适用 | 关键字段 |
|---|---|---|
| `webdav` | NAS / Alist / 坚果云 / Nextcloud | `endpoint`（集合目录，带尾斜杠）、`username/password` |
| `http` | 自建接收 PUT 的服务 | `endpoint`、可选 `token`（Bearer）与 `headers` |
| `s3` | S3 / MinIO / RustFS / OSS 兼容 | `endpoint`（自托管必填）、`s3_bucket`、`s3_prefix`、`access_key/secret_key`（需 `pip install boto3`） |

3. 上传（增量，自动跳过已传；`--dry` 预览 / `--force` 全量重传）：

```bash
python upload/upload_images.py
```

4. 上传成功且 `auto_switch_site_to_remote=true` 时，脚本会把 `site.config.json`
   的 `image_base_url` 自动切到你的外网地址；再跑一次构建即完成切换：

```bash
python generator/build.py
```

之后文章页所有图片都引用 `https://你的域名/<slug>/图片文件`，`site/images/` 只是本地兜底，
不再随部署分发。

## 重新构建 / 配置

`site.config.json`：

```json
{
  "site_name": "鳄鱼文库",
  "site_en": "GATOR LIBRARY",
  "image_base_url": "images",
  "source_site": "https://gator.ronchy2000.top/",
  "disclaimer": "内容仅供信息交流，不构成任何投资建议；原文版权归原作者所有。"
}
```

改完运行 `python generator/build.py`。`--images` 参数可只同步图片目录。

## 站点功能

- **首页**：概览 + 四大分类卡片 + 最新更新
- **分类页**：每日信息 / 每日复盘 / 随笔 按月分组；历史研报页带 宏观/行业/其他 筛选
- **归档页**：按年折叠的时间线
- **文章页**：衬线长文排版、阅读进度条、微信原文链接、同分类上一篇/下一篇
- **搜索**：`Ctrl/⌘ + K` 或任意搜索框唤起；标题与正文全文检索，关键词高亮，`↑↓` 选择、`Enter` 打开（索引懒加载，约 3-5MB）
- **主题**：浅色（暖纸）/ 暗黑（暖黑）双主题，右上角切换，跟随系统偏好，localStorage 记忆

## 部署

`site/` 是纯静态目录，任意静态托管都可以：Nginx、Caddy、OSS/COS 静态网站、
GitHub Pages、Cloudflare Pages、EdgeOne Pages 等。无后端、无构建时依赖。

**云服务器（Nginx）三步**，详见 `deploy/` 目录：

```bash
# 1. 服务器装 nginx（Ubuntu: apt install nginx；CentOS: yum install nginx）
#    把 deploy/nginx.conf.example 传到 /etc/nginx/conf.d/gator.conf，改 server_name
#    sudo nginx -t && sudo systemctl reload nginx

# 2. 本机一键推送（Git Bash 里执行；首次全量，之后增量只传变化的 tar）
./deploy/deploy.sh root@你的服务器IP
#    图片已上传文件服务器的话，主体只有 ~35MB：
#    SKIP_IMAGES=1 ./deploy/deploy.sh root@你的服务器IP

# 3. HTTPS（有域名时）
sudo certbot --nginx -d 你的域名
```

日常更新 = 重爬 + 重建 + 重推：

```bash
python crawler/crawl.py && python generator/build.py && ./deploy/deploy.sh root@服务器IP
```

也可以用 Xftp/WinSCP 把 `site/` 目录直接拖到服务器站点目录，效果相同。

## 合规说明

- 内容爬取自公开归档站（robots.txt 允许），仅限个人学习与信息备份用途；
- 原文版权归「获得信息差」「像鳄鱼一样思考」及各研报原作者所有；
- 请勿公开部署或二次分发内容本身；公开部署请自行获得授权。
- 爬虫限速 ~6 req/s，请勿调高并发压源站。

## 增量更新源站新文章

```bash
python crawler/crawl.py       # sitemap 增量，只爬新的
python generator/build.py     # 重新生成站点
```

建议配合任务计划（每周一次）长期维护。

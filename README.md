# iHub

自托管个人数字生活中枢。把短信、邮箱与设备通知收进同一条消息时间线，并在同一个站点里提供音乐、影视、书架、文件、常用导航与容器管理。

数据、账号与密钥都在自己的机器上，一个容器、一个数据目录即可运行。

> 官网：https://ihub.olim.top · 文档：https://ihub.olim.top/docs/

## 功能与特性

- **单容器、数据自持**：后端直接托管前端，一个容器、一个数据目录即可运行；数据、账号与密钥都在自己的机器上。
- **多用户隔离**：首个注册账号自动成为管理员，用户之间的消息、来源、头像、设备与媒体数据相互隔离。
- **一站式**：消息、音乐、影视、书架、文件、导航与容器共用一个账号与数据目录。
- **消息中心**：短信、邮箱与 API 通知聚合，渠道筛选、全文搜索、未读、星标、置顶、批量操作、回收站，SSE 实时更新。
- **总览**：消息、导航、快传、容器与继续阅读一屏呈现。
- **头像库**：企业分组 + 匹配规则，按号码 / 签名 / 邮箱 / 昵称匹配，支持 ZIP 导入导出。
- **音乐**：NAS 本地曲库或 Subsonic，歌词、收藏、歌单、每日推荐、热歌排行与全屏播放。
- **影视**：NAS 本地片库或 Jellyfin / Emby，NFO 元数据、TMDB 海报与剧照补全、继续观看。
- **书架**：TXT / EPUB / PDF / MOBI / AZW3 / FB2，阅读进度按账号同步。
- **文件**：逻辑目录、分片上传、在线预览、批量移动与下载，电脑 / 手机 / NAS 之间中转。
- **导航**：双地址、图标补全、分组与拖拽排序。
- **容器**：状态、资源占用与日志，可选启停、重启、删除、拉取镜像（默认关闭）。
- **数据管理**：消息保留期、30 天回收站、附件自动回收；备份一个目录即备份全部。

## 目录

```text
app/                  FastAPI 后端源码
scripts/              冒烟 / 回归测试与运维脚本
frontend-dist/        前端构建产物（后端直接托管）
Dockerfile            单容器镜像定义
docker-compose.yml    源码构建部署编排
requirements.txt      Python 依赖
LICENSE               许可协议
```

前端构建产物已经在 `frontend-dist/` 中，部署不需要 Node.js。

## 环境要求

- **Docker 部署**：Docker Engine 20+，Compose v2；建议 1GB 以上内存。
- **源码运行**：Python 3.11+。
- 一个空闲端口，默认 `18765`。
- 可选：NAS 媒体目录、Subsonic / Navidrome、Jellyfin / Emby、TMDB API Key、Docker Socket。

## 安装与使用

### Docker Compose

```bash
git clone https://github.com/limi75525/ihub.git
cd ihub
docker compose up -d --build
```

打开 `http://<主机IP>:18765`，首次访问注册的第一个账号自动成为管理员。

- 容器名 `ihub`，宿主端口 `18765` 映射到容器 `8000`。
- 数据默认在仓库下的 `./data`；备份该目录即备份全部数据。
- 后端必须以单 worker 运行，不要用 `--workers` 扩容。

其他部署方式（官方镜像、NAS、反向代理、环境变量、升级与备份）见官方文档：

https://ihub.olim.top/docs/

### 源码运行

```bash
cd ihub
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux / macOS 用 .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 18765 --no-proxy-headers
```

`--no-proxy-headers` 不要省略：uvicorn 默认会自行改写客户端 IP，与登录锁定、推送限流的计数口径冲突。

## 安全

- 登录使用 JWT + bcrypt；改密码后旧 token 立即失效。
- 设备推送使用 HMAC-SHA256 签名，带时间窗与 nonce 防重放；设备密钥可随时重置。
- 邮箱授权码、音乐 / 影视源密码等敏感字段使用 Fernet 加密存储。
- 邮件 HTML 在 sandbox iframe 中渲染；上传与导入有类型和体积上限。
- 容器监控与控制默认关闭；Docker Socket 约等于宿主机最高权限，请只在内网使用。

## 链接

- 官网：https://ihub.olim.top
- 文档：https://ihub.olim.top/docs/
- GitHub：https://github.com/limi75525/ihub
- 问题反馈：https://github.com/limi75525/ihub/issues

## 许可

Copyright (c) 2026 [Limi](https://www.olim.top)。

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)（署名—非商业性使用 4.0 国际）许可：

- 允许个人使用、自托管、学习、修改与分享；
- 必须保留原作者署名（Limi / https://www.olim.top），并注明是否修改；
- **不得用于商业用途**。

完整条款见 [LICENSE](LICENSE)。CC BY-NC 4.0 属于「源码公开、非商业许可」，不是 OSI 定义的开源许可证；如需商业授权，请先联系作者。

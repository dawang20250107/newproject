# 性能优化部署说明（3M 带宽 / 4 核 4G / 100 人并发）

本次优化目标：3M 固定带宽下让 100 人同时使用更顺畅。瓶颈排序是
**带宽 > 后端并发 > 其它**，所以收益最大的是「nginx gzip 压缩」和
「gunicorn 改 gevent 异步」两项。

代码/配置已改好，下面是你需要在**服务器上手动执行**的步骤。
全程不影响日报系统（8080）。

---

## 1. nginx：开启 gzip（传输量降约 70%，收益最大）

`deploy/nginx.conf` 顶部已新增 `gzip on` 等指令。注意 **gzip 是 http{} 级指令**：

- 推荐放到 `/etc/nginx/nginx.conf` 的 `http { ... }` 块内（全站生效，日报系统也受益）；
- 或放到站点 `server { ... }` 块顶部（仅本站生效）也可以。

把 `deploy/nginx.conf` 里这一段（`gzip on` 到 `gzip_types ...;`）复制过去，然后：

```bash
sudo nginx -t          # 语法检查，必须 OK
sudo systemctl reload nginx
```

**验证 gzip 生效**（看到 `content-encoding: gzip` 即成功）：

```bash
curl -s -I -H "Accept-Encoding: gzip" https://kxtshare.cloud/paikuan/assets/index-*.js \
  | grep -i content-encoding
```

> 说明：本次还顺手把已下线的独立财务分析前端 `/caiwu/` 改成 301 跳转到
> `/paikuan/#/caiwu/report`（前端已整合进排款平台）。`/api/cw/` 接口仍保留代理。

---

## 2. gunicorn：改 gevent 异步 worker（并发从 3 → 数千）

`requirements.txt` 已加 `gevent==24.2.1`，`deploy/paikuan.service` 已改为
`-w 4 -k gevent --worker-connections 1000`。

```bash
# 装新依赖
/opt/paikuan/venv/bin/pip install -r /opt/paikuan/backend/requirements.txt

# 更新 systemd 服务并重启
sudo cp /opt/paikuan/backend/deploy/paikuan.service /etc/systemd/system/paikuan.service
sudo systemctl daemon-reload
sudo systemctl restart paikuan

# 确认起来了
systemctl status paikuan --no-pager
```

**为什么是 `-w 4 -k gevent` 而不是 `-w 9` 同步**：
- 同步 worker：1 个请求独占 1 个 worker 直到返回。有人导出 Excel（几秒），
  就占住一个名额，其他人排队。9 个 worker 也只能扛 9 个并发慢请求。
- gevent：每个 worker 进程用协程并发处理上千连接，慢请求（等 DB、等
  DeepSeek AI、生成大表）不阻塞同进程的其它请求。4 进程吃满 4 核，
  并发上限 4×1000=4000，对 100 人绰绰有余。
- 兼容性：项目用纯 Python 的 PyMySQL 驱动，天然兼容 gevent 猴子补丁，
  业务代码不用改。

---

## 3. MySQL：确认连接数（并发上来后的唯一隐患）

gevent 并发高时，并发 DB 连接也会变多。MySQL 默认 `max_connections=151`，
配合 `CONN_MAX_AGE=60`（已设，连接会复用）通常够用。若高峰日志里出现
`Too many connections`，调高即可：

```ini
# /etc/mysql/mysql.conf.d/mysqld.cnf 的 [mysqld] 段
max_connections = 300
```
```bash
sudo systemctl restart mysql
```

---

## 4. 前端：登录轮询退避（已含在新构建里）

待审批用户的登录页轮询从「每 3 秒」改为「5s 起、指数退避到 30s、
后台标签暂停」。100 个待审批用户挂在登录页时，请求量从 ~33 req/s
降到峰值 ~3 req/s 且持续衰减。无需额外操作，随前端一起发布。

---

## 发布前端

```bash
# 本地已 npm run build，产物在 backend/frontend_dist/
sudo rsync -a --delete /opt/paikuan/backend/frontend_dist/ /opt/paikuan/frontend_dist/
# index.html 不缓存（nginx 已配 no-store），用户刷新即拿到新版
```

---

## 效果预期

| 项目 | 优化前 | 优化后 |
|---|---|---|
| 首屏传输量（首次访问） | ~720 KB 原文 | ~250 KB（gzip） |
| 二次访问静态资源 | 重新下载 | 命中强缓存，几乎 0 下载 |
| 后端并发慢请求 | 3 个就排队 | 数百并发不阻塞 |
| 待审批登录页请求压力 | 33 req/s（100人） | 峰值 ~3 req/s 且衰减 |

带宽仍是物理上限：100 人**同时首次**冷加载仍会瓜分 3M。但有了 gzip +
强缓存，日常使用（已缓存静态资源、只走 API JSON）体验会顺畅很多。
若预算允许，带宽升到 10M 是对 100 人体验提升最直接的一步。

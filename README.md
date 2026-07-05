# 集团财务管理平台

业财融合的财务管理系统，覆盖应收账款、资金排款付款、经营驾驶舱三大业务域。
后端 Django（单一计算正源），前端 Vue 3，前端构建产物随后端一同部署。

## 技术栈

- **后端**：Django + Django REST 风格视图，按业务域拆分应用（`ar` / `caiwu` / `paikuan`）
- **前端**：Vue 3（Composition API）+ Vite，源码在 `frontend/`，构建产物提交于 `backend/frontend_dist/` 由 Django 直接服务
- **鉴权**：JWT，登录后每个受保护请求重载当前用户并校验在职/审批状态、岗位权限、事业部隔离

## 目录结构

```
backend/
  ar/        应收账款域 —— 应收台账、回款、差额调整、账龄、周期报表、现金流、资金池
  caiwu/     财务分析域 —— 经营数据、利润表、预算、驾驶舱、知识库
  paikuan/   排款付款域 —— 审批管理、排款管理、付款管理（与应收双向同步留痕）
  frontend_dist/   前端构建产物（npm run build 生成，随后端部署）
frontend/
  src/       Vue 3 源码（视图、组件、API 封装、组合式函数）
```

## 本地开发

```bash
# 后端
cd backend
python manage.py migrate
python manage.py runserver

# 前端（开发热更新）
cd frontend
npm install
npm run dev

# 前端构建（产物输出到 backend/frontend_dist/，需提交）
cd frontend
npm run build
```

## 测试

```bash
cd backend
python manage.py test          # 全量
python manage.py test ar       # 指定业务域
```

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 部署核对清单（每次发布必过）

1. **数据库迁移**（漏跑 = 线上 500）：
   ```bash
   cd backend && python manage.py migrate
   ```
2. **环境变量必填**（生产缺省会拒绝启动或降级）：

   | 变量 | 说明 |
   |---|---|
   | `DJANGO_SECRET_KEY` | 生产密钥（用默认值时生产环境拒绝启动） |
   | `JWT_SECRET` | 登录令牌签名密钥 |
   | `MYSQL_ADDRESS` / `MYSQL_USERNAME` / `MYSQL_PASSWORD` | 生产库（未设则回落 SQLite 开发库） |
   | `DEEPSEEK_API_KEY` | 财务分析 AI（缺省则 AI 功能不可用，其余正常） |
   | `DEEPSEEK_FALLBACK_MODEL`（可选） | 主模型异常时的降级模型，默认 `deepseek-chat` |
   | `SEARCH_PROVIDER` / `SEARCH_API_KEY`（可选） | AI 联网搜索默认内置必应中国抓取、**无需配置**；如需更稳定可切 `bocha`（博查）或 `serper`（Google） |
   | `SENTRY_DSN`（可选） | 错误上报；`PROMETHEUS_ENABLED`（可选）开 /metrics |
3. **前端产物**：`cd frontend && npm run build`（产物写入 `backend/frontend_dist/`，需一并提交/部署）。
4. **发布后验证**：访问 `/healthz`（存活）与 `/readyz`（数据库连通）均应返回 200；登录后抽查付款管理列表可加载。
5. **定时任务**（CloudRun 定时触发器 / crontab，每日凌晨）：
   ```bash
   python manage.py pk_housekeeping     # 回收站清理等幂等维护
   python manage.py pk_aging_digest    # 账龄/逾期摘要（文本输出，可接邮件/机器人）
   ```
   同行/行业自动调研（建议每周，AI 搜索→提炼→查重→沉淀知识库，内置搜索无需 Key）：
   ```bash
   python manage.py agent_research
   ```
   AI 助手回归评测（改提示词/换模型后手动跑，只读）：
   ```bash
   python manage.py eval_agent --year 2026 --month 5   # 黄金问题集 + 数字对账器
   ```

## 角色操作速查

| 职务 | 高频操作路径 |
|---|---|
| **出纳** | 付款管理 → 勾选 → 批量付款；「剩余」列**核销**角标 → 选预付 → 核销（无需预收预付页面权限）；右键行 → 预付核销/反向核销 |
| **结算会计** | 应收明细 → 录入回款/开票；预收核销在「预收预付」页；回款超未收时先做差额调整或转预收 |
| **财务BP/总监** | 审批管理 → 批量审批 → 批量排款；运输对账单导入 → 一键排款；驾驶舱看现金流/资金池 |
| **超管** | 权限配置 → 勾选后可「预览此职务视角」验证；回收站还原/彻底删除；侧边栏底部切换深浅色/表格密度 |

通用技巧：侧边栏「**单号直达**」粘贴一个或一批单号（空格/换行/+/逗号等任意分隔）回车即定位；表格按住 **Shift** 点击可区间勾选；列头 ⏷ 筛选可保存为**方案**（含列显隐/列宽，跟随账号云同步）。

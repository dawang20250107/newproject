# Change Log

## 2026-06-27

### Paikuan system

- **待办中心 + 通知中心**：
  - 新页「待办中心」（`/workbench`）：待审批/待排款/今日到期/逾期/超预算 待办桶，
    可拖拽排序（localStorage 持久化），点击跳转对应列表，「按事业部」展开部门联动明细。
  - 全局右上角通知铃铛：未读徽标 + 60s 轮询，下拉通知流、标记已读、点击跳转。
  - 后端 `Notification` 模型（迁移 0031）+ `_workbench_buckets` 共享引擎 +
    懒生成（用户活动时按部门作用域 dedup 生成）+ `pk_generate_notifications` 定时命令。
- 表格密度切换（紧凑/适中/宽松），CSS 变量驱动、localStorage 持久化、侧边栏一键循环。
- 排款超预算预警：排款弹窗实时联动本月预算余量，超支橙色警示（`/approvals/budget-check`）。
- 软删 + 回收站：审批/付款批量删除改软删，新增回收站页可还原/彻底删除（`/trash/*`）。
- 统一空/错/加载状态插画体系：EmptyState 升级为 SVG 线性插画（空/错误/加载/无结果/无权限）。
- 大数据量异步导出：同步导出超 5000 行自动转后台任务，完成后自动下载（`/exports/*`）。
- 定时维护命令（供外部 cron 调用）：
  - `python manage.py pk_housekeeping` — 回收站自动清理（默认 30 天）+ 导出任务清理（默认 7 天）。
  - `python manage.py pk_aging_digest` — 逾期未付 + 本月预算预警日报（支持 `--json`）。
  - 建议 crontab：`0 3 * * * … pk_housekeeping`，`30 8 * * 1-5 … pk_aging_digest`。

## 2026-05-26

### Paikuan system

- Hardened AR backend writes so project, receivable, payment, and budget create/update/delete endpoints enforce job permissions server-side.
- Scoped AR budget detail operations by delivery department, preventing cross-department read/update/delete by direct record ID.
- Filtered AR project and receivable Excel exports by AR field visibility permissions.
- Fixed new AR receivable creation so derived tax/outstanding calculations do not read child payments before the record has a primary key.
- Added AR regression tests covering write permissions, budget department isolation, export field masking, payment-field visibility, and receivable calculation updates.

## 2026-05-25

### Caiwu system

- Added backend regression coverage for the core financial calculation chain: L1 formula rows, department-detail-only report aggregation, same-period publish replacement rules, waterfall bridge deltas, and closed-period Kingdee ledger parsing.

### Paikuan system

- Hardened backend request auth so JWT role, job title, and department claims are no longer trusted after login; each protected request reloads the current user and checks active/approved status.
- Fixed payment update permission handling by filtering non-editable fields before merge and amount validation, preventing hidden fields from bypassing overpayment checks.
- Added payments-page permission checks to payment template, import, export, and departments endpoints.
- Updated the payment edit modal to submit only fields the current user can edit when modifying an existing payment.
- Added backend regression tests for stale tokens, department changes, overpayment validation, hidden non-editable fields, and related endpoint permissions.

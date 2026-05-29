// Single source of truth for lists/labels shared across multiple views.
export const DEPARTMENTS = [
  '集团总部', '劳务事业部', '运输事业部', '自营事业部',
  '阔展事业部', '多式联运事业部', '供应链事业部',
]

export const ROLE_LABELS = {
  super_admin: '超级管理员',
  manager: '财务经理',
  operator: '操作员',
  viewer: '查看员',
}

export const JOB_LABELS = {
  finance_director: '财务总监',
  finance_bp: '财务BP',
  chief_cashier: '总出纳',
  cashier: '出纳',
  general_manager: '总经理',
  gm_assistant: '总经理助理',
  settlement_accountant: '结算会计',
  sales_bp: '销售BP',
}

export const JOB_OPTIONS = [
  { v: 'finance_director', label: '财务总监' },
  { v: 'finance_bp', label: '财务BP' },
  { v: 'chief_cashier', label: '总出纳' },
  { v: 'cashier', label: '出纳' },
  { v: 'general_manager', label: '总经理' },
  { v: 'gm_assistant', label: '总经理助理' },
  { v: 'settlement_accountant', label: '结算会计' },
  { v: 'sales_bp', label: '销售BP' },
]

// ── UTC+8 时间工具 ────────────────────────────────────────────────────────────
// 系统所有日期/时间基准强制 UTC+8（北京时间），不依赖浏览器系统时区设置。

/** 返回 UTC+8 今日日期，格式 YYYY-MM-DD。 */
export function todayCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10)
}

/** 返回 UTC+8 当前小时（0-23），用于时段问候语。 */
export function hourCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCHours()
}

/** 返回 UTC+8 当前年份。 */
export function yearCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCFullYear()
}

/** 返回 UTC+8 当前月份（1-12）。 */
export function monthCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCMonth() + 1
}

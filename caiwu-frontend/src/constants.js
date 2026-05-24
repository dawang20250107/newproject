export const BUSINESS_UNITS = [
  '集团总部', '劳务事业部', '运输事业部', '自营事业部',
  '阔展事业部', '多式联运事业部', '供应链事业部',
]

export const ROLE_LABELS = {
  super_admin: '超级管理员',
  manager: '财务经理',
  operator: '操作员',
  viewer: '查看员',
  general_manager: '总经理',
}

export const JOB_LABELS = {
  finance_director: '财务总监',
  finance_bp: '财务BP',
  general_manager: '总经理',
}

export const JOB_OPTIONS = [
  { v: 'finance_director', label: '财务总监' },
  { v: 'finance_bp', label: '财务BP' },
  { v: 'general_manager', label: '总经理' },
]

// UTC+8 utilities — forced regardless of browser timezone
export function todayCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10)
}
export function hourCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCHours()
}
export function yearCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCFullYear()
}
export function monthCST() {
  return new Date(Date.now() + 8 * 3600 * 1000).getUTCMonth() + 1
}

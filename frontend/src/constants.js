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
}

export const JOB_OPTIONS = [
  { v: 'finance_director', label: '财务总监' },
  { v: 'finance_bp', label: '财务BP' },
  { v: 'chief_cashier', label: '总出纳' },
  { v: 'cashier', label: '出纳' },
]

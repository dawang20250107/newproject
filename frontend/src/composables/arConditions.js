// 应收明细筛选条件的字段目录 + 描述助手。FilterPanel 与 ARRecords 的 chip 栏共用，
// 保证字段/标签单一来源。条件对象形如：
//   { t:'dim',  field, value }
//   { t:'date', field, range, exclude, start, end }
//   { t:'amt',  field, op, value, min, max }

export const STATUS_OPTS = [
  { v: 'overdue', l: '逾期' }, { v: 'current', l: '当期' }, { v: 'not_due', l: '未到期' },
  { v: 'settled', l: '已结清' }, { v: 'outstanding', l: '未结清' },
]
export const RECON_OPTS = [{ v: '已对账', l: '已对账' }, { v: '未对账', l: '未对账' }]
export const INVOICE_OPTS = [{ v: '未开票', l: '未开票' }, { v: '已开票', l: '已开票' }, { v: '已结清', l: '已结清' }]
export const RESP_OPTS = [
  { v: 'recon', l: '对账阶段' }, { v: 'invoice', l: '待开票' }, { v: 'post', l: '票后回款' }, { v: 'settled', l: '已结清' },
]
export const SHARED_OPTS = [{ v: '1', l: '共享' }, { v: '0', l: '非共享' }]

// 维度字段：kind 决定值编辑器（select 固定选项 / dept / year / month / text）
export const DIM_FIELDS = [
  { field: 'dept', label: '事业部', kind: 'dept' },
  { field: 'operation_year', label: '运作年', kind: 'year' },
  { field: 'operation_month', label: '运作月', kind: 'month' },
  { field: 'status', label: '状态', kind: 'select', opts: STATUS_OPTS },
  { field: 'reconciliation_status', label: '对账状态', kind: 'select', opts: RECON_OPTS },
  { field: 'invoice_status', label: '开票状态', kind: 'select', opts: INVOICE_OPTS },
  { field: 'responsibility', label: '责任阶段', kind: 'select', opts: RESP_OPTS },
  { field: 'is_shared', label: '共享', kind: 'select', opts: SHARED_OPTS },
  { field: 'manager', label: '负责人', kind: 'text' },
  // 'q'（项目/负责人/编号 模糊）由页面常驻快捷搜索框承载，不在面板内重复提供
]
export const DATE_FIELDS = [
  { field: 'due_date', label: '应收到期' },
  { field: 'payment_date', label: '回款日期' },
  { field: 'invoice_date', label: '开票日期' },
  { field: 'reconciliation_date', label: '对账日期' },
]
export const AMT_FIELDS = [
  { field: 'estimated_amount', label: '预估金额' },
  { field: 'outstanding_amount', label: '未收金额' },
  { field: 'tax_amount', label: '税额' },
  { field: 'actual_invoice_amount', label: '开票额' },
  { field: 'account_diff_adjustment', label: '账实差额' },
]
export const DATE_RANGES = [
  { v: 'this_week', l: '本周' }, { v: 'this_month', l: '本月' }, { v: 'last_month', l: '上月' },
  { v: 'next_month', l: '下月' }, { v: 'this_year', l: '本年' }, { v: 'last_year', l: '去年' },
  { v: 'custom', l: '自定义' },
]
export const AMT_OPS = [
  { v: 'ne0', l: '≠0' }, { v: 'eq0', l: '=0' }, { v: 'gt0', l: '>0' }, { v: 'lt0', l: '<0' },
  { v: 'gt', l: '>' }, { v: 'lt', l: '<' }, { v: 'between', l: '区间' },
]

const _find = (list, field) => list.find(f => f.field === field) || {}
const _lbl = (opts, v) => (opts.find(o => o.v === v) || {}).l || v

// 一句话描述某条件，用于 chip 展示
export function describeCondition(c) {
  if (!c || !c.t) return ''
  if (c.t === 'dim') {
    if (c.field === 'project_id') return '指定项目'   // 仅经深链创建，不在菜单
    const f = _find(DIM_FIELDS, c.field)
    let val = c.value
    if (f.kind === 'select') val = _lbl(f.opts || [], c.value)
    else if (c.field === 'operation_month') val = `${c.value}月`
    return `${f.label || c.field}: ${val}`
  }
  if (c.t === 'date') {
    const f = _find(DATE_FIELDS, c.field)
    const rng = c.range === 'custom' ? `${c.start || '…'}~${c.end || '…'}` : _lbl(DATE_RANGES, c.range)
    return `${f.label || c.field} ${c.exclude ? '不含' : ''}${rng}`
  }
  if (c.t === 'amt') {
    const f = _find(AMT_FIELDS, c.field)
    let opTxt = _lbl(AMT_OPS, c.op)
    if (c.op === 'between') opTxt = `${c.min || '…'}~${c.max || '…'}`
    else if (['gt', 'lt', 'eq'].includes(c.op)) opTxt = `${opTxt}${c.value || ''}`
    return `${f.label || c.field} ${opTxt}`
  }
  return ''
}

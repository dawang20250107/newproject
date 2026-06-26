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

// 维度字段：kind 决定值编辑器（select 固定选项 / dept / year / ym / text）
export const DIM_FIELDS = [
  { field: 'dept', label: '事业部', kind: 'dept' },
  { field: 'operation_year', label: '运作年', kind: 'year' },
  { field: 'operation_ym', label: '运作年月', kind: 'ym' },
  { field: 'status', label: '状态', kind: 'select', opts: STATUS_OPTS },
  { field: 'reconciliation_status', label: '对账状态', kind: 'select', opts: RECON_OPTS },
  { field: 'invoice_status', label: '开票状态', kind: 'select', opts: INVOICE_OPTS },
  { field: 'responsibility', label: '责任阶段', kind: 'select', opts: RESP_OPTS },
  { field: 'is_shared', label: '共享', kind: 'select', opts: SHARED_OPTS },
  { field: 'manager', label: '负责人', kind: 'text' },
  // 'q'（项目/负责人/编号 模糊）由页面常驻快捷搜索框承载，不在面板内重复提供
]
export const DATE_FIELDS = [
  { field: 'operation_date', label: '运作日期' },
  { field: 'due_date', label: '应收到期' },
  { field: 'target_collection_date', label: '目标回款日期' },
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
  { v: 'this_week', l: '本周' }, { v: 'last_week', l: '上周' },
  { v: 'this_month', l: '本月' }, { v: 'last_month', l: '上月' },
  { v: 'this_quarter', l: '本季度' }, { v: 'last_quarter', l: '上季度' },
  { v: 'this_year', l: '本年' }, { v: 'last_year', l: '去年' },
  { v: 'next_month', l: '下月' }, { v: 'custom', l: '自定义' },
]
export const AMT_OPS = [
  { v: 'ne0', l: '≠0' }, { v: 'eq0', l: '=0' }, { v: 'gt0', l: '>0' }, { v: 'lt0', l: '<0' },
  { v: 'gt', l: '>' }, { v: 'lt', l: '<' }, { v: 'eq', l: '=' }, { v: 'ne', l: '≠' },
  { v: 'between', l: '区间' }, { v: 'empty', l: '为空' }, { v: 'not_empty', l: '不为空' },
]

const _find = (list, field) => list.find(f => f.field === field) || {}
const _lbl = (opts, v) => (opts.find(o => o.v === v) || {}).l || v

// 一句话描述某条件，用于 chip 展示
export function describeCondition(c) {
  if (!c || !c.t) return ''
  // 条件组（括号）：内部以 且/或 连接，整体加括号展示，如「(预估>0 且 未开票)」
  if (c.t === 'group') {
    const conn = c.match === 'any' ? ' 或 ' : ' 且 '
    const inner = (c.conditions || []).map(describeCondition).filter(Boolean).join(conn)
    return `(${inner})`
  }
  if (c.t === 'dim') {
    if (c.field === 'project_id') return '指定项目'   // 仅经深链创建，不在菜单
    const f = _find(DIM_FIELDS, c.field)
    let val = c.value
    // 多选：value 为数组 → 各值取标签后以「/」连接（如「状态: 逾期 / 已结清」）
    if (Array.isArray(c.value)) {
      val = c.value.map(x => f.kind === 'select' ? _lbl(f.opts || [], x) : x).join(' / ')
    }
    else if (f.kind === 'select') val = _lbl(f.opts || [], c.value)
    else if (c.field === 'operation_month') val = `${c.value}月`
    else if (c.field === 'operation_ym') {
      // 区间(start~end) + 含/不含；end 为空时退化为单月
      const rng = (c.end && c.end !== c.value) ? `${c.value}~${c.end}` : c.value
      return `运作年月 ${c.exclude ? '不含 ' : ''}${rng}`
    }
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
    else if (['gt', 'lt', 'eq', 'ne'].includes(c.op)) opTxt = `${opTxt}${c.value || ''}`
    return `${f.label || c.field} ${opTxt}`
  }
  return ''
}

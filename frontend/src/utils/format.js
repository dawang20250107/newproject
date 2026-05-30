// 统一的展示格式化工具。各页面原本各自实现了一份金额/时间格式化，
// 行为略有差异（小数位、单位空格、是否带「元」、是否启用「亿」等），
// 这里收敛成一份可配置实现，组件内保留各自的薄封装名以零改模板。

/**
 * 自适应金额格式化：超 1 亿用「亿」，超 1 万用「万」，否则原值。
 * @param {*} v 金额（数字或可解析字符串）
 * @param {object} [opts]
 * @param {number} [opts.decimals=2] 大单位（万/亿）保留的小数位
 * @param {boolean} [opts.space=false] 单位前是否加空格（如 "12.34 万"）
 * @param {boolean} [opts.yuan=false] 万元以下是否带「元」后缀
 * @param {boolean} [opts.yi=true] 是否启用「亿」（false 时大额只用万）
 * @param {boolean} [opts.smallRound=false] 万元以下是否取整（否则两位小数）
 * @param {string} [opts.dash='—'] 空值/非数字占位
 */
export function fmtCompact(v, opts = {}) {
  const { decimals = 2, space = false, yuan = false, yi = true, smallRound = false, dash = '—' } = opts
  const n = parseFloat(v)
  if (!isFinite(n)) return dash
  const abs = Math.abs(n)
  const sp = space ? ' ' : ''
  if (yi && abs >= 1e8) return (n / 1e8).toFixed(decimals) + sp + '亿'
  if (abs >= 1e4) return (n / 1e4).toFixed(decimals) + sp + '万'
  if (smallRound) return String(Math.round(n))
  return n.toFixed(2) + (yuan ? sp + '元' : '')
}

/** 千分位 + 两位小数，不带单位（用于表格金额列）。非数字回退 fallback。 */
export function fmtMoney(v, fallback = '0.00') {
  const n = parseFloat(v)
  if (!isFinite(n)) return fallback
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 百分比：带正负号、一位小数。非数字回退 dash。 */
export function fmtPct(v, dash = '—') {
  const n = parseFloat(v)
  if (!isFinite(n)) return dash
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%'
}

/** 日期时间本地化（24 小时制）。空/非法回退 dash。 */
export function fmtTime(s, dash = '') {
  if (!s) return dash
  const d = new Date(s)
  if (isNaN(d.getTime())) return dash
  return d.toLocaleString('zh-CN', { hour12: false })
}

/** 紧凑日期时间（月日 时:分）。空回退 '-'。 */
export function fmtDateTime(s, dash = '-') {
  if (!s) return dash
  const d = new Date(s)
  if (isNaN(d.getTime())) return dash
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

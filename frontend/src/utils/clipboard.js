// 统一的剪贴板写入。优先用异步 Clipboard API，在非安全上下文（http/局域网 IP）
// 或旧浏览器下回退到 execCommand('copy')，保证内网部署也能复制。

/**
 * 复制纯文本到剪贴板。
 * @param {string} text 待复制文本
 * @returns {Promise<boolean>} 是否成功
 */
export async function copyText(text) {
  const s = text == null ? '' : String(text)
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(s)
      return true
    }
  } catch (_) { /* 回退到 execCommand */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = s
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.style.top = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch (_) {
    return false
  }
}

/**
 * 把一行记录复制为「Tab 分隔」文本，可直接粘贴进 Excel/表格。
 * @param {object} row 记录对象
 * @param {Array<{key:string,label?:string,format?:(v:any,row:object)=>any}>} cols 列定义
 * @param {object} [opts]
 * @param {boolean} [opts.header=false] 是否在前面加一行表头
 * @returns {Promise<boolean>}
 */
export function copyRowTSV(row, cols, opts = {}) {
  const cell = (c) => {
    const raw = row?.[c.key]
    const v = c.format ? c.format(raw, row) : raw
    return v == null ? '' : String(v).replace(/[\t\n\r]/g, ' ')
  }
  const body = cols.map(cell).join('\t')
  const text = opts.header
    ? cols.map(c => c.label ?? c.key).join('\t') + '\n' + body
    : body
  return copyText(text)
}

/**
 * 把多行记录复制为「Tab 分隔 + 换行」的表格文本（含表头）。
 * @param {object[]} rows 记录数组
 * @param {Array<{key:string,label?:string,format?:(v:any,row:object)=>any}>} cols 列定义
 * @returns {Promise<boolean>}
 */
export function copyRowsTSV(rows, cols) {
  const head = cols.map(c => c.label ?? c.key).join('\t')
  const lines = rows.map(row =>
    cols.map(c => {
      const raw = row?.[c.key]
      const v = c.format ? c.format(raw, row) : raw
      return v == null ? '' : String(v).replace(/[\t\n\r]/g, ' ')
    }).join('\t')
  )
  return copyText([head, ...lines].join('\n'))
}

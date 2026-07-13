// 操作记忆统一入口：本机偏好（localStorage）小工具。
// 约定：值一律 JSON；读失败/脏数据回退 fallback，绝不抛错打断页面。
// 命名：ar_* / cw_* / pk_* 前缀按域区分；跟账号走的偏好请用服务端方案（useTableSchemes），
// 这里只放「机器级」习惯（上次选的方式/账户/Tab/部门等）。

export function loadPref(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    const v = JSON.parse(raw)
    return v == null ? fallback : v
  } catch { return fallback }
}

export function savePref(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* 隐私模式等场景静默 */ }
}

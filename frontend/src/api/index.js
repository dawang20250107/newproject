import axios from 'axios'

const api = axios.create({
  baseURL: '/api/pk',
  timeout: 15000,
})

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('pk_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`

  // Auto-inject active-department scope (skip when caller already set dept or depts)
  try {
    const raw = JSON.parse(localStorage.getItem('pk_active_depts') || '[]')
    if (Array.isArray(raw) && raw.length > 0) {
      cfg.params = cfg.params || {}
      const hasDepts = cfg.params.depts !== undefined && cfg.params.depts !== ''
      const hasDept = cfg.params.dept !== undefined && cfg.params.dept !== ''
      if (!hasDepts && !hasDept) {
        cfg.params.depts = raw.join(',')
      }
    }
  } catch {}
  return cfg
})

api.interceptors.response.use(
  res => res.data,
  async err => {
    // 被竞态车道取消的请求：不是真错误，回传统一标记供调用方静默忽略
    if (axios.isCancel?.(err) || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
      return Promise.reject({ __canceled: true })
    }
    if (err.response?.status === 401) {
      localStorage.removeItem('pk_token')
      localStorage.removeItem('pk_user')
      localStorage.removeItem('pk_perms')
      window.location.href = '/paikuan/#/login'
    }
    // Blob-typed requests that error return a Blob body rather than JSON.
    // Parse it back so callers always receive a plain error object.
    let errData = err.response?.data
    if (errData instanceof Blob && errData.type?.includes('json')) {
      try { errData = JSON.parse(await errData.text()) } catch {}
    }
    // Backend error payloads use {code, error}. Normalize to expose `.msg`
    // so callers can uniformly read `e?.msg` for the human-readable reason.
    if (errData && typeof errData === 'object') {
      if (errData.msg === undefined && errData.error !== undefined) {
        errData.msg = errData.error
      }
    } else if (!errData) {
      errData = { msg: err.message || '网络错误' }
    }
    return Promise.reject(errData || err)
  }
)

export default api

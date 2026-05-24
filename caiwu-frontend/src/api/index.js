import axios from 'axios'

const api = axios.create({
  baseURL: '/api/cw',
  timeout: 20000,
})

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('cw_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  res => res.data,
  async err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('cw_token')
      localStorage.removeItem('cw_user')
      localStorage.removeItem('cw_perms')
      window.location.href = '/caiwu/#/login'
    }
    let errData = err.response?.data
    // A blob (e.g. a failed Excel export) may actually carry a JSON error body.
    if (errData instanceof Blob && errData.type?.includes('json')) {
      try { errData = JSON.parse(await errData.text()) } catch {}
    }
    // Proper backend error envelope: { code, error }
    if (errData && typeof errData === 'object' && errData.error) {
      return Promise.reject(errData)
    }
    // Otherwise the failure is transport-level (no JSON body): surface a
    // diagnostic message so deployment problems are obvious instead of a
    // generic "操作失败".
    const status = err.response?.status
    let msg
    if (!err.response) {
      msg = '无法连接服务器，请检查网络后重试'
    } else if (status === 404) {
      msg = '接口不存在（404），请检查后端服务配置'
    } else if (status === 502 || status === 503 || status === 504) {
      msg = `后端服务暂不可用（${status}），请稍后重试`
    } else if (status >= 500) {
      msg = `服务器内部错误（${status}）`
    } else {
      msg = `请求失败（${status}）`
    }
    return Promise.reject({ code: status || -1, error: msg })
  },
)

export default api

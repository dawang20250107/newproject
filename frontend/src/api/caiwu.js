import axios from 'axios'

// Financial-analysis (caiwu) API. Shares the paikuan login/token (pk_token):
// accounts and permissions were unified into the paikuan platform (Stage 2+3).
const api = axios.create({
  baseURL: '/api/cw',
  timeout: 20000,
})

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('pk_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  res => res.data,
  async err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('pk_token')
      localStorage.removeItem('pk_user')
      localStorage.removeItem('pk_perms')
      window.location.href = '/paikuan/#/login'
    }
    let errData = err.response?.data
    // A blob (e.g. a failed Excel export) may actually carry a JSON error body.
    if (errData instanceof Blob && errData.type?.includes('json')) {
      try { errData = JSON.parse(await errData.text()) } catch {}
    }
    if (errData && typeof errData === 'object' && errData.error) {
      if (errData.msg === undefined) errData.msg = errData.error
      return Promise.reject(errData)
    }
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
    return Promise.reject({ code: status || -1, error: msg, msg })
  },
)

export default api

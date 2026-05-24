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
    if (errData instanceof Blob && errData.type?.includes('json')) {
      try { errData = JSON.parse(await errData.text()) } catch {}
    }
    return Promise.reject(errData || err)
  },
)

export default api

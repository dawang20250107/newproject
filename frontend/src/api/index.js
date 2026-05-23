import axios from 'axios'

const api = axios.create({
  baseURL: '/api/pk',
  timeout: 15000,
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
    // Blob-typed requests that error return a Blob body rather than JSON.
    // Parse it back so callers always receive a plain error object.
    let errData = err.response?.data
    if (errData instanceof Blob && errData.type?.includes('json')) {
      try { errData = JSON.parse(await errData.text()) } catch {}
    }
    return Promise.reject(errData || err)
  }
)

export default api

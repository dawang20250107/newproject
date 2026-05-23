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
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('pk_token')
      localStorage.removeItem('pk_user')
      window.location.href = '/paikuan/#/login'
    }
    return Promise.reject(err.response?.data || err)
  }
)

export default api

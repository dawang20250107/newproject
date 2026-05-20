const API_BASE = 'https://kxtshare.cloud'

App({
  globalData: {
    apiBase: API_BASE,
    token: '',
    profile: null,
  },

  onLaunch() {
    this._restoreSession()
  },

  _restoreSession() {
    try {
      const token = wx.getStorageSync('kxt_token')
      const profile = wx.getStorageSync('kxt_profile')
      if (token) this.globalData.token = token
      if (profile) this.globalData.profile = profile
    } catch (e) {}
  },

  // 仅供 splash 页调用，外部禁止调用
  _silentLogin() {
    if (this.globalData.token) {
      return Promise.resolve(this.globalData.token)
    }
    if (this._loginPromise) {
      return this._loginPromise
    }
    this._loginPromise = this._doLoginInternal()
    this._loginPromise.finally(() => {
      this._loginPromise = null
    })
    return this._loginPromise
  },

  _doLoginInternal() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: (loginRes) => {
          if (!loginRes.code) {
            reject(new Error('wx.login 未返回 code'))
            return
          }
          wx.request({
            url: API_BASE + '/api/login',
            method: 'POST',
            data: { code: loginRes.code },
            header: { 'Content-Type': 'application/json' },
            success: (r) => {
              if (r.statusCode === 200 && r.data && r.data.token) {
                this.globalData.token = r.data.token
                this.globalData.profile = r.data.profile || null
                wx.setStorageSync('kxt_token', r.data.token)
                wx.setStorageSync('kxt_profile', r.data.profile || null)
                resolve(r.data.token)
              } else {
                const errMsg = (r.data && r.data.error) ? r.data.error : 'login failed'
                reject(new Error(errMsg))
              }
            },
            fail: (err) => {
              reject(new Error(err.errMsg || 'network error'))
            },
          })
        },
        fail: (err) => {
          reject(new Error(err.errMsg || 'wx.login failed'))
        },
      })
    })
  },
})

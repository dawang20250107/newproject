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

  async _silentLogin(force) {
    if (this.globalData.token && !force) return this.globalData.token
    if (this._loginPromise) return this._loginPromise

    this._loginPromise = this._doLoginInternal()
    try {
      const token = await this._loginPromise
      return token
    } finally {
      this._loginPromise = null
    }
  },

  async _doLoginInternal() {
    const maxAttempts = 3
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const code = await new Promise((resolve, reject) => {
          wx.login({
            success: (res) => {
              if (res.code) resolve(res.code)
              else reject(new Error('wx.login failed'))
            },
            fail: reject,
          })
        })

        const result = await new Promise((resolve, reject) => {
          wx.request({
            url: API_BASE + '/api/login',
            method: 'POST',
            data: { code },
            header: { 'Content-Type': 'application/json' },
            success: (r) => {
              if (r.statusCode === 200 && r.data && r.data.token) {
                resolve(r.data)
              } else {
                const errMsg = (r.data && r.data.error) ? r.data.error : 'login failed'
                reject(new Error(errMsg))
              }
            },
            fail: reject,
          })
        })

        this.globalData.token = result.token
        this.globalData.profile = result.profile || null
        wx.setStorageSync('kxt_token', result.token)
        wx.setStorageSync('kxt_profile', result.profile || null)
        return result.token

      } catch (e) {
        const errMsg = e.message || String(e)
        if (errMsg.includes('code been used') && attempt < maxAttempts) {
          await new Promise(r => setTimeout(r, 3000))
          continue
        }
        throw e
      }
    }
    throw new Error('login failed after max attempts')
  },
})

const API_BASE = 'https://dailyreport-248461-6-1371772686.sh.run.tcloudbase.com'

App({
  globalData: {
    apiBase: API_BASE,
    token: '',
    profile: null,
  },

  onLaunch() {
    this._restoreSession()
    this._silentLogin()
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
    this._loginPromise = new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (!res.code) return reject(new Error('wx.login failed'))
          wx.request({
            url: API_BASE + '/api/login',
            method: 'POST',
            data: { code: res.code },
            header: { 'Content-Type': 'application/json' },
            success: (r) => {
              if (r.statusCode === 200 && r.data && r.data.token) {
                this.globalData.token = r.data.token
                this.globalData.profile = r.data.profile || null
                wx.setStorageSync('kxt_token', r.data.token)
                wx.setStorageSync('kxt_profile', r.data.profile || null)
                resolve(r.data.token)
              } else {
                reject(r.data || new Error('login failed'))
              }
            },
            fail: reject,
          })
        },
        fail: reject,
      })
    }).finally(() => { this._loginPromise = null })
    return this._loginPromise
  },
})

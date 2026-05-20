const app = getApp()
const MAX_RETRIES = 3

Page({
  data: {
    statusText: '正在连接...',
    tapCount: 0,
    pressed: false,
    retryCount: 0,
    showRetryBtn: false,
  },

  onLoad() {
    this._doLogin()
  },

  onTapSplash() {
    const count = this.data.tapCount + 1
    this.setData({ tapCount: count, pressed: true })
    wx.vibrateShort({ type: 'light' })
    setTimeout(() => this.setData({ pressed: false }), 200)
  },

  onTapRetry() {
    this.setData({ showRetryBtn: false, retryCount: 0, statusText: '正在连接...' })
    this._doLogin()
  },

  _doLogin() {
    const minDelay = new Promise(resolve => setTimeout(resolve, 1500))

    Promise.all([this._tryLoginOnce(), minDelay])
      .then(() => {
        this.setData({ statusText: '进入中 ✨' })
        setTimeout(() => {
          wx.switchTab({ url: '/pages/report/index' })
        }, 400)
      })
      .catch((err) => {
        const errMsg = (err && (err.message || err.errMsg)) ? (err.message || err.errMsg) : String(err)
        const retryCount = this.data.retryCount + 1
        if (retryCount < MAX_RETRIES) {
          this.setData({
            statusText: '连接失败，' + (MAX_RETRIES - retryCount) + '秒后重试...',
            retryCount: retryCount,
          })
          setTimeout(() => {
            if (this.data.showRetryBtn) return
            this.setData({ statusText: '正在重试...' })
            this._doLogin()
          }, 5000)
        } else {
          this.setData({
            statusText: '连接失败：' + errMsg,
            showRetryBtn: true,
          })
        }
      })
  },

  // 单次登录尝试，失败时自动重试一次（针对 code been used）
  _tryLoginOnce() {
    return app._silentLogin().catch((err) => {
      const errMsg = err.message || String(err)
      // 如果是 code been used，等3秒后重试一次
      if (errMsg.includes('code been used')) {
        return new Promise((resolve, reject) => {
          setTimeout(() => {
            app._loginPromise = null
            app.globalData.token = ''
            app._silentLogin().then(resolve).catch(reject)
          }, 3000)
        })
      }
      throw err
    })
  },
})

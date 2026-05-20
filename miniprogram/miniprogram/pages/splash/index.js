const app = getApp()
const MAX_RETRIES = 3

Page({
  _isLoggingIn: false,

  data: {
    statusText: '正在连接...',
    tapCount: 0,
    pressed: false,
    retryCount: 0,
    showRetryBtn: false,
  },

  onLoad() {
    if (!this._isLoggingIn) {
      this._doLogin()
    }
  },

  onTapSplash() {
    const count = this.data.tapCount + 1
    this.setData({ tapCount: count, pressed: true })
    wx.vibrateShort({ type: 'light' })
    setTimeout(() => this.setData({ pressed: false }), 200)
  },

  onTapRetry() {
    this.setData({ showRetryBtn: false, retryCount: 0, statusText: '正在连接...' })
    this._isLoggingIn = false
    this._doLogin()
  },

  async _doLogin() {
    if (this._isLoggingIn) return
    this._isLoggingIn = true

    const minDelay = new Promise(resolve => setTimeout(resolve, 1500))
    try {
      await Promise.all([app._silentLogin(), minDelay])
      this.setData({ statusText: '进入中 ✨' })
      setTimeout(() => {
        wx.switchTab({ url: '/pages/report/index' })
      }, 400)
    } catch (e) {
      const retryCount = this.data.retryCount + 1
      if (retryCount < MAX_RETRIES) {
        this.setData({
          statusText: '连接失败，' + (MAX_RETRIES - retryCount) + '秒后重试...',
          retryCount: retryCount,
        })
        setTimeout(() => {
          if (this.data.showRetryBtn) return
          this.setData({ statusText: '正在重试...' })
          this._isLoggingIn = false
          this._doLogin()
        }, 5000)
      } else {
        this.setData({
          statusText: '无法连接服务器',
          showRetryBtn: true,
        })
        this._isLoggingIn = false
      }
    }
  },
})

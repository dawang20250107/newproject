const app = getApp()
const MAX_RETRIES = 5

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

  async _doLogin() {
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
          this._doLogin()
        }, 2000)
      } else {
        this.setData({
          statusText: '无法连接服务器',
          showRetryBtn: true,
        })
      }
    }
  },
})

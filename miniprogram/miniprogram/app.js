const tcbConfig = require('./utils/tcbconfig.js');

App({
  globalData: {
    apiBase: 'https://kxtshare.cloud',
    userInfo: null,
    tcbEnvId: tcbConfig.ENV_ID,
  },
  onLaunch() {
    console.log('KXT 小程序启动');
    if (wx.cloud) {
      wx.cloud.init({ env: tcbConfig.ENV_ID, traceUser: true });
      console.log('CloudBase 初始化完成，环境:', tcbConfig.ENV_ID);
    }
    // Silent login: get openid-based JWT if no token stored
    const token = wx.getStorageSync('kxt_token');
    if (!token) {
      this._silentLogin();
    }
  },

  _silentLogin() {
    return new Promise((resolve, reject) => {
      wx.login({
        success: (res) => {
          if (!res.code) { reject(new Error('wx.login failed')); return; }
          wx.request({
            url: this.globalData.apiBase + '/api/auth/wx-login',
            method: 'POST',
            header: { 'Content-Type': 'application/json' },
            data: { code: res.code },
            success: (resp) => {
              if (resp.statusCode === 200 && resp.data && resp.data.token) {
                wx.setStorageSync('kxt_token', resp.data.token);
                console.log('静默登录成功');
                resolve(resp.data.token);
              } else {
                const msg = (resp.data && resp.data.error) || '静默登录失败';
                console.error(msg);
                reject(new Error(msg));
              }
            },
            fail: reject,
          });
        },
        fail: reject,
      });
    });
  },
});

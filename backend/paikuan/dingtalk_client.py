"""钉钉 OpenAPI 轻客户端 —— 审批同步取数用。

只做"薄"一层：拿 access_token（带缓存）、手机号/姓名换人、列审批模板、
按模板+时间+人拉审批实例 ID、拉实例详情。每个方法把钉钉返回解析成朴素 dict，
上层（dingtalk_sync）不碰 HTTP，便于 mock 测试。

所有密钥仅来自 settings（环境变量）。网络/接口异常抛 DingTalkError，上层转友好错误。
"""
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class DingTalkError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {'token': '', 'exp': 0.0}   # access_token 有效期 7200s，提前 300s 续


def _base():
    return getattr(settings, 'DINGTALK_BASE_URL', 'https://oapi.dingtalk.com')


def _fetch_token_new(key, secret):
    """新版开放平台 oauth2（Client ID/Secret）。返回 (token, ttl秒)。"""
    r = requests.post('https://api.dingtalk.com/v1.0/oauth2/accessToken',
                      json={'appKey': key, 'appSecret': secret}, timeout=10)
    data = r.json()
    if data.get('accessToken'):
        return data['accessToken'], int(data.get('expireIn', 7200))
    raise DingTalkError(data.get('message') or data.get('errmsg') or str(data))


def _fetch_token_old(key, secret):
    """旧版 gettoken（AppKey/AppSecret）。返回 (token, ttl秒)。"""
    r = requests.get(f'{_base()}/gettoken',
                     params={'appkey': key, 'appsecret': secret}, timeout=10)
    data = r.json()
    if data.get('errcode') == 0 and data.get('access_token'):
        return data['access_token'], int(data.get('expires_in', 7200))
    raise DingTalkError(data.get('errmsg') or str(data))


def access_token():
    """获取并缓存 access_token（进程内缓存，提前 5 分钟过期）。
    先试新版 oauth2 端点（新开放平台应用），失败再试旧版 gettoken——两者拿到的
    access_token 可通用于新旧 API。凭证做 strip，规避环境变量里的换行/空格。"""
    now = time.time()
    with _TOKEN_LOCK:
        if _TOKEN_CACHE['token'] and now < _TOKEN_CACHE['exp']:
            return _TOKEN_CACHE['token']
    key = (settings.DINGTALK_APP_KEY or '').strip()
    secret = (settings.DINGTALK_APP_SECRET or '').strip()
    if not (key and secret):
        raise DingTalkError('钉钉未配置（缺少 AppKey/AppSecret）')
    errs = []
    for fn in (_fetch_token_new, _fetch_token_old):
        try:
            token, ttl = fn(key, secret)
            with _TOKEN_LOCK:
                _TOKEN_CACHE['token'] = token
                _TOKEN_CACHE['exp'] = now + max(60, ttl - 300)
            return token
        except Exception as ex:
            errs.append(str(ex)[:120])
    raise DingTalkError('获取钉钉 token 失败：' + '；'.join(errs))


def _post(path, body):
    try:
        r = requests.post(f'{_base()}{path}', params={'access_token': access_token()},
                          json=body, timeout=15)
        data = r.json()
    except DingTalkError:
        raise
    except Exception as ex:
        raise DingTalkError(f'钉钉接口调用失败：{str(ex)[:120]}')
    ec = data.get('errcode')
    if ec not in (0, None):
        raise DingTalkError(f'{data.get("errmsg") or data}', code=ec)
    return data


# ── 人员 ────────────────────────────────────────────────────────────────────
def userid_by_mobile(mobile):
    """手机号 → userid（唯一）。查不到返回 None。"""
    mobile = (mobile or '').strip()
    if not mobile:
        return None
    try:
        data = _post('/topapi/v2/user/getbymobile', {'mobile': mobile})
    except DingTalkError as ex:
        # 仅"该手机号不在通讯录"才当查无此人（errcode 60121 等）；
        # token/权限/网络等配置类错误必须上抛，避免掩盖成"找不到该人"。
        s = str(ex)
        if ex.code in (60121, 60011) or '找不到' in s or '不存在' in s:
            logger.info('dingtalk getbymobile miss: %s', ex)
            return None
        raise
    return (data.get('result') or {}).get('userid')


def user_detail(userid):
    """userid → {name, dept_ids, dept_names}。最佳努力。"""
    data = _post('/topapi/v2/user/get', {'userid': userid})
    res = data.get('result') or {}
    return {
        'userid': userid,
        'name': res.get('name', ''),
        'dept_ids': res.get('dept_id_list') or [],
        'title': res.get('title', ''),
    }


def _dept_ids_all():
    """遍历部门树，返回全部部门 id（含根 1）。缓存 10 分钟。"""
    ids, queue = [1], [1]
    while queue:
        pid = queue.pop()
        data = _post('/topapi/v2/department/listsub', {'dept_id': pid})
        for d in (data.get('result') or []):
            ids.append(d['dept_id'])
            queue.append(d['dept_id'])
    return ids


_USER_DIR = {'exp': 0.0, 'rows': []}    # [{userid,name,dept}]
_USER_DIR_LOCK = threading.Lock()


def _user_directory():
    """全员通讯录（userid/name/dept 简表），缓存 10 分钟，供姓名搜索。"""
    now = time.time()
    with _USER_DIR_LOCK:
        if _USER_DIR['rows'] and now < _USER_DIR['exp']:
            return _USER_DIR['rows']
    rows = []
    for dept_id in _dept_ids_all():
        cursor = 0
        while True:
            data = _post('/topapi/v2/user/list',
                         {'dept_id': dept_id, 'cursor': cursor, 'size': 100})
            res = data.get('result') or {}
            for u in (res.get('list') or []):
                rows.append({'userid': u.get('userid'), 'name': u.get('name', ''),
                             'dept': dept_id})
            if not res.get('has_more'):
                break
            cursor = res.get('next_cursor', 0)
    # 去重（一人多部门）
    seen, uniq = set(), []
    for r in rows:
        if r['userid'] and r['userid'] not in seen:
            seen.add(r['userid'])
            uniq.append(r)
    with _USER_DIR_LOCK:
        _USER_DIR['rows'] = uniq
        _USER_DIR['exp'] = now + 600
    return uniq


def users_by_name(name):
    """姓名 → 候选人列表 [{userid,name}]（可能多个同名，交前端选择）。"""
    name = (name or '').strip()
    if not name:
        return []
    return [{'userid': r['userid'], 'name': r['name']}
            for r in _user_directory() if name in (r['name'] or '')]


# ── 审批模板 ──────────────────────────────────────────────────────────────────
def list_process_codes():
    """列出要纳入同步的审批模板 [{process_code,name}]。
    优先用 settings.DINGTALK_PROCESS_CODES（"code:名称,code:名称" 或纯 code 逗号分隔）；
    未配置时尝试 API 枚举（按管理员可见模板，best-effort）。"""
    raw = (getattr(settings, 'DINGTALK_PROCESS_CODES', '') or '').strip()
    if raw:
        out = []
        for seg in raw.split(','):
            seg = seg.strip()
            if not seg:
                continue
            if ':' in seg:
                code, nm = seg.split(':', 1)
                out.append({'process_code': code.strip(), 'name': nm.strip()})
            else:
                out.append({'process_code': seg, 'name': seg})
        return out
    admin = (getattr(settings, 'DINGTALK_ADMIN_USERID', '') or '').strip()
    if not admin:
        return []
    out = []
    try:
        data = _post('/topapi/process/listbyuserid', {'userid': admin})
        for p in ((data.get('result') or {}).get('process_list') or []):
            out.append({'process_code': p.get('process_code'), 'name': p.get('name', '')})
    except DingTalkError as ex:
        logger.warning('list_process_codes API failed: %s', ex)
    return out


# ── 审批实例 ──────────────────────────────────────────────────────────────────
def list_instance_ids(process_code, start_ms, end_ms, userid=None):
    """按模板+时间区间(+发起人/参与人)拉审批实例 ID（自动翻页）。"""
    ids, cursor = [], 0
    while True:
        body = {'process_code': process_code, 'start_time': int(start_ms),
                'end_time': int(end_ms), 'cursor': cursor, 'size': 20}
        if userid:
            body['userid_list'] = userid
        data = _post('/topapi/processinstance/listids', body)
        res = data.get('result') or {}
        ids.extend(res.get('list') or [])
        nxt = res.get('next_cursor')
        if nxt is None:
            break
        cursor = nxt
    return ids


def get_instance(instance_id):
    """拉单个审批实例详情（原始 result dict）。"""
    data = _post('/topapi/processinstance/get', {'process_instance_id': instance_id})
    res = data.get('process_instance') or data.get('result') or {}
    res['_instance_id'] = instance_id
    return res

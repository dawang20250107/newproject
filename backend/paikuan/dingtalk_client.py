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


_API_NEW = 'https://api.dingtalk.com'


def _new(method, path, params=None, json_body=None):
    """新版 OpenAPI（api.dingtalk.com，x-acs-dingtalk-access-token 头）。
    成功返回解析后的 dict；HTTP≥400 或 success=false 抛 DingTalkError（含钉钉 message）。"""
    try:
        r = requests.request(
            method, f'{_API_NEW}{path}',
            headers={'x-acs-dingtalk-access-token': access_token(),
                     'Content-Type': 'application/json'},
            params=params, json=json_body, timeout=15)
        data = r.json() if r.content else {}
    except DingTalkError:
        raise
    except Exception as ex:
        raise DingTalkError(f'钉钉接口调用失败：{str(ex)[:120]}')
    if r.status_code >= 400 or data.get('success') is False:
        raise DingTalkError(data.get('message') or data.get('errmsg') or f'HTTP {r.status_code}',
                            code=data.get('code'))
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


def users_by_name(name):
    """姓名 → 候选人列表 [{userid,name}]（可能多个同名，交前端选择）。
    新版通讯录搜索接口（服务端搜索，避免遍历全员超时）。"""
    name = (name or '').strip()
    if not name:
        return []
    data = _new('POST', '/v1.0/contact/users/search',
                json_body={'queryWord': name, 'offset': 0, 'size': 10})
    uids = data.get('list')
    if uids is None:
        raise DingTalkError(data.get('message') or data.get('errmsg')
                            or '姓名搜索失败（需通讯录搜索权限）')
    out = []
    for uid in uids[:10]:
        try:
            out.append({'userid': uid, 'name': user_detail(uid).get('name') or uid})
        except DingTalkError:
            out.append({'userid': uid, 'name': uid})
    return out


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
    try:
        return templates_by_user(admin)
    except DingTalkError as ex:
        logger.warning('list_process_codes API failed: %s', ex)
        return []


def templates_by_user(userid=None):
    """列出审批模板 [{process_code,name,dir_name}]（新版 workflow 接口，nextToken 分页）。
    userId 省略（userid=None）→ 返回「企业下全部表单」（覆盖报销等审批人不可发起的模板）；
    传入 → 该用户「可发起」范围。首页 nextToken 传 '0'。"""
    out, seen, next_token = [], set(), '0'
    for _ in range(200):   # 分页兜底（全企业模板可能较多）
        params = {'nextToken': next_token, 'maxResults': 100}
        if userid:
            params['userId'] = userid
        data = _new('GET', '/v1.0/workflow/processes/userVisibilities/templates', params=params)
        res = data.get('result')
        # 兼容 result 为 dict（含分页）或直接为模板数组两种返回形态
        if isinstance(res, list):
            plist, res = res, {}
        else:
            res = res or {}
            plist = res.get('processList') or res.get('templateList') or res.get('list') or []
        for p in plist:
            code = p.get('processCode') or p.get('process_code')
            if code and code not in seen:
                seen.add(code)
                out.append({'process_code': code, 'name': p.get('name', ''),
                            'dir_name': p.get('dirName') or p.get('dir_name') or ''})
        next_token = res.get('nextToken')
        if not next_token:
            break
    return out


def all_templates():
    """企业下全部审批模板（userId 省略）。报销等模板务必用此拿全。"""
    return templates_by_user(None)


# ── 审批实例（新版 workflow 接口）──────────────────────────────────────────────
def list_instance_ids(process_code, start_ms, end_ms, userid=None, statuses=None):
    """按模板+时间区间(+发起人/+状态)拉审批实例 ID（新版 instanceIds/query，nextToken 翻页）。
    userid：按「发起人」过滤（userIds，最多 10 个）。statuses：RUNNING/TERMINATED/COMPLETED 过滤。
    注意：钉钉限制单次时间跨度≤120 天，超范围需由上层分段调用。"""
    ids, next_token = [], 0   # nextToken 必填：首页 0（Long 游标）
    for _ in range(2000):     # 上限兜底
        body = {'processCode': process_code, 'startTime': int(start_ms),
                'endTime': int(end_ms), 'nextToken': next_token, 'maxResults': 20}
        if userid:
            body['userIds'] = [userid]
        if statuses:
            body['statuses'] = list(statuses)
        data = _new('POST', '/v1.0/workflow/processes/instanceIds/query', json_body=body)
        res = data.get('result') or {}
        ids.extend(res.get('list') or [])
        next_token = res.get('nextToken')
        if not next_token:
            break
    return ids


def _norm_instance(r, instance_id):
    """新版实例详情（camelCase）归一为下游映射用的 snake_case 结构。
    新版用 operationRecords + approverUserIds 表达处理轨迹（无 tasks 数组），一并归一。"""
    return {
        '_instance_id': instance_id,
        'business_id': r.get('businessId') or '',
        'title': r.get('title') or '',
        'originator_userid': r.get('originatorUserId') or '',
        'originator_dept_name': r.get('originatorDeptName') or '',
        'status': r.get('status') or '',
        'result': r.get('result') or '',
        'create_time': r.get('createTime') or '',
        'finish_time': r.get('finishTime') or '',
        'approver_userids': r.get('approverUserIds') or [],
        'cc_userids': r.get('ccUserIds') or [],
        'form_component_values': [
            {'name': c.get('name', ''), 'value': c.get('value', ''),
             'component_type': c.get('componentType', '')}
            for c in (r.get('formComponentValues') or []) if isinstance(c, dict)
        ],
        'operation_records': [
            {'userid': o.get('userId', ''), 'type': (o.get('type') or ''),
             'result': (o.get('result') or ''), 'date': o.get('date', '')}
            for o in (r.get('operationRecords') or []) if isinstance(o, dict)
        ],
        # 新版通常无 tasks；若返回则一并归一（向后兼容）
        'tasks': [
            {'userid': t.get('userId', ''), 'task_status': t.get('status', ''),
             'result': t.get('result', '')}
            for t in (r.get('tasks') or []) if isinstance(t, dict)
        ],
    }


def get_instance(instance_id):
    """拉单个审批实例详情（新版 processInstances），归一为下游可用的 dict。"""
    data = _new('GET', '/v1.0/workflow/processInstances',
                params={'processInstanceId': instance_id})
    res = data.get('result') or data.get('processInstance') or {}
    return _norm_instance(res, instance_id)

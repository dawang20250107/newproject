import json
import datetime
import logging
import urllib.request as urllib_req
import urllib.error
from functools import wraps

import jwt
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from wxcloudrun.models import UserProfile, DailyReport

logger = logging.getLogger('wxcloudrun')


# ─── 工具函数 ─────────────────────────────────────────────

def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def _make_token(profile, hours=168):
    payload = {
        'uid': profile.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=hours),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


def jwt_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth.startswith('Bearer '):
            return _json({'error': '未登录'}, 401)
        try:
            payload = jwt.decode(auth[7:], settings.JWT_SECRET, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return _json({'error': 'token已过期，请重新登录'}, 401)
        except jwt.InvalidTokenError:
            return _json({'error': 'token无效'}, 401)
        try:
            request.profile = UserProfile.objects.get(id=payload['uid'])
        except UserProfile.DoesNotExist:
            return _json({'error': '用户不存在'}, 401)
        return view_func(request, *args, **kwargs)
    return wrapper


def _profile_dict(p):
    return {
        'display_name': p.display_name,
        'dept': p.dept,
        'role': p.role,
        'name': p.name,
    }


# ─── 主页 ─────────────────────────────────────────────────

def index(request):
    return _json({'code': 0, 'msg': 'KXT 小程序后端运行中', 'version': '1.0.0'})


# ─── 登录 ─────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST'])
def wx_login(request):
    """POST /api/login — 用 wx.login 的 code 换 openid + JWT"""
    try:
        body = json.loads(request.body)
        code = body.get('code', '').strip()
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    if not code:
        return _json({'error': 'code不能为空'}, 400)
    if not settings.WX_APPID or not settings.WX_SECRET:
        return _json({'error': '服务端未配置微信AppID/Secret'}, 500)

    url = (
        'https://api.weixin.qq.com/sns/jscode2session'
        f'?appid={settings.WX_APPID}&secret={settings.WX_SECRET}'
        f'&js_code={code}&grant_type=authorization_code'
    )
    try:
        with urllib_req.urlopen(url, timeout=10) as resp:
            wx_data = json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f'[wx_login] 微信接口失败: {e}')
        return _json({'error': f'微信接口调用失败: {e}'}, 502)

    if wx_data.get('errcode'):
        return _json({'error': wx_data.get('errmsg', '微信登录失败')}, 400)
    openid = wx_data.get('openid')
    if not openid:
        return _json({'error': '获取openid失败'}, 400)

    profile, _ = UserProfile.objects.get_or_create(openid=openid)
    return _json({
        'token': _make_token(profile),
        'profile': _profile_dict(profile),
    })


# ─── 用户档案 ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'PUT'])
@jwt_required
def profile(request):
    """GET/PUT /api/profile"""
    p = request.profile
    if request.method == 'GET':
        return _json({'profile': _profile_dict(p)})
    try:
        body = json.loads(request.body)
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    for field in ('display_name', 'dept', 'role', 'name'):
        if field in body:
            setattr(p, field, body[field] or '')
    p.save()
    return _json({'ok': True, 'profile': _profile_dict(p)})


# ─── 日报 CRUD ────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'PUT'])
@jwt_required
def report_detail(request, date):
    """GET/PUT /api/reports/<YYYY-MM-DD>"""
    p = request.profile
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        return _json({'error': '日期格式错误'}, 400)

    if request.method == 'GET':
        try:
            r = DailyReport.objects.get(user=p, date=d)
            return _json({
                'date': date,
                'blocks': r.blocks,
                'works': r.works,
                'not_works': r.not_works,
                'plans': r.plans,
                'commit_text': r.commit_text,
                'updated_at': r.updated_at.isoformat(),
            })
        except DailyReport.DoesNotExist:
            return _json({
                'date': date,
                'blocks': [],
                'works': '',
                'not_works': '',
                'plans': '',
                'commit_text': '',
                'updated_at': None,
            })

    try:
        body = json.loads(request.body)
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    r, _ = DailyReport.objects.get_or_create(user=p, date=d)
    r.blocks = body.get('blocks', [])
    r.works = body.get('works', '') or ''
    r.not_works = body.get('not_works', '') or ''
    r.plans = body.get('plans', '') or ''
    r.commit_text = body.get('commit_text', '') or ''
    r.save()
    return _json({'ok': True, 'updated_at': r.updated_at.isoformat()})


@csrf_exempt
@require_http_methods(['GET'])
@jwt_required
def report_dates(request):
    """GET /api/reports/dates?year=&month= — 月历红点"""
    p = request.profile
    try:
        year = int(request.GET['year'])
        month = int(request.GET['month'])
    except (KeyError, ValueError):
        return _json({'error': '需要 year 和 month 参数'}, 400)
    dates = DailyReport.objects.filter(
        user=p, date__year=year, date__month=month
    ).values_list('date', flat=True)
    return _json({'dates': [d.isoformat() for d in dates]})


@csrf_exempt
@require_http_methods(['GET'])
@jwt_required
def report_week(request):
    """GET /api/reports/week?date= — 周分析（周一到周日）"""
    p = request.profile
    date_str = request.GET.get('date', datetime.date.today().isoformat())
    try:
        anchor = datetime.date.fromisoformat(date_str)
    except ValueError:
        return _json({'error': '日期格式错误'}, 400)
    monday = anchor - datetime.timedelta(days=anchor.weekday())
    sunday = monday + datetime.timedelta(days=6)
    reports = {
        r.date: r for r in DailyReport.objects.filter(user=p, date__gte=monday, date__lte=sunday)
    }
    labels = ['一', '二', '三', '四', '五', '六', '日']
    days = []
    total_mins = 0
    total_done = 0
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        r = reports.get(d)
        mins = 0
        done = []
        if r:
            for blk in r.blocks:
                s, e = blk.get('start', ''), blk.get('end', '')
                if s and e:
                    try:
                        sh, sm = map(int, s.split(':'))
                        eh, em = map(int, e.split(':'))
                        m = (eh * 60 + em) - (sh * 60 + sm)
                        if m > 0:
                            mins += m
                    except Exception:
                        pass
                for t in blk.get('tasks', []):
                    if t.get('progress', 0) >= 100 and (t.get('desc') or '').strip():
                        done.append(t['desc'].strip())
            total_mins += mins
            total_done += len(done)
        days.append({
            'date': d.isoformat(),
            'weekday': labels[i],
            'has_report': r is not None,
            'completed_tasks': done,
            'hours': round(mins / 60, 1),
        })
    return _json({
        'week_start': monday.isoformat(),
        'week_end': sunday.isoformat(),
        'days': days,
        'total_hours': round(total_mins / 60, 1),
        'completed_count': total_done,
    })


# ─── AI 分析 ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST'])
@jwt_required
def analysis(request):
    """POST /api/analysis — 调用 Claude 分析周报或月报"""
    if not settings.CLAUDE_API_KEY:
        return _json({'error': '未配置 AI 密钥，请在 .env 设置 CLAUDE_API_KEY'}, 503)

    try:
        body = json.loads(request.body)
    except Exception:
        return _json({'error': '请求格式错误'}, 400)

    analysis_type = body.get('type', 'week')
    date_str = body.get('date', datetime.date.today().isoformat())
    p = request.profile
    user_name = p.name or p.display_name or '同学'

    try:
        anchor = datetime.date.fromisoformat(date_str)
    except ValueError:
        return _json({'error': '日期格式错误'}, 400)

    if analysis_type == 'week':
        monday = anchor - datetime.timedelta(days=anchor.weekday())
        sunday = monday + datetime.timedelta(days=6)
        reports = DailyReport.objects.filter(
            user=p, date__gte=monday, date__lte=sunday
        ).order_by('date')
        records = [
            {'日期': str(r.date), '时段任务': r.blocks,
             '行得通的是': r.works, '行不通的是': r.not_works,
             '明日计划': r.plans}
            for r in reports
        ]
        range_str = f'{monday} ～ {sunday}'
        prompt = (
            f"你是 {user_name} 的效能教练。以下是本周（{range_str}）的日报数据：\n\n"
            f"{json.dumps(records, ensure_ascii=False, indent=2)}\n\n"
            "请生成一份**简洁有力的周报总结**，使用中文，格式如下：\n\n"
            "## 本周亮点\n- （2-3条核心成就）\n\n"
            "## 遇到的挑战\n- （及解决思路）\n\n"
            "## 时间效率\n（有效工时分析）\n\n"
            "## 下周重点\n- （1-3个建议方向）\n\n"
            "## 一句话激励\n（鼓励的话）\n\n"
            "语言简洁精准，避免废话，字数控制在400字以内。"
        )
    elif analysis_type == 'month':
        from calendar import monthrange
        year, month = anchor.year, anchor.month
        _, last_day = monthrange(year, month)
        first_day = datetime.date(year, month, 1)
        last_date = datetime.date(year, month, last_day)
        reports = DailyReport.objects.filter(
            user=p, date__gte=first_day, date__lte=last_date
        ).order_by('date')
        records = [
            {'日期': str(r.date), '时段任务': r.blocks,
             '行得通的是': r.works, '行不通的是': r.not_works}
            for r in reports
        ]
        range_str = f'{year}年{month}月（共{len(records)}天有记录）'
        prompt = (
            f"你是 {user_name} 的效能教练。以下是{range_str}的日报数据：\n\n"
            f"{json.dumps(records, ensure_ascii=False, indent=2)}\n\n"
            "请生成一份**月度成长报告**，使用中文，格式如下：\n\n"
            "## 本月核心成就 Top3\n\n"
            "## 反复出现的挑战\n\n"
            "## 工作模式洞察\n（高效日/低效日规律）\n\n"
            "## 下月优化建议\n\n"
            "## 月度激励语\n\n"
            "语言简洁，字数控制在500字以内。"
        )
    else:
        return _json({'error': '不支持的分析类型，仅支持 week / month'}, 400)

    req_payload = json.dumps({
        'model': settings.CLAUDE_MODEL,
        'max_tokens': 1024,
        'messages': [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')

    req = urllib_req.Request(
        'https://api.anthropic.com/v1/messages',
        data=req_payload,
        headers={
            'x-api-key': settings.CLAUDE_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        },
    )
    try:
        with urllib_req.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
        text = result['content'][0]['text']
        return _json({'ok': True, 'analysis': text, 'type': analysis_type, 'range': range_str})
    except urllib_req.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        logger.error(f'[analysis] Claude API 错误 {e.code}: {err_body}')
        return _json({'error': f'AI 服务错误 ({e.code})'}, 500)
    except Exception as e:
        logger.error(f'[analysis] 分析失败: {e}')
        return _json({'error': f'分析失败: {str(e)}'}, 500)

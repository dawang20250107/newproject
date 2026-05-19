import json
import datetime
import urllib.request as urllib_req
from functools import wraps

import jwt
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from wxcloudrun.models import UserProfile, DailyReport


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def jwt_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth.startswith('Bearer '):
            return _json({'error': '未登录'}, 401)
        token = auth[7:]
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return _json({'error': 'token已过期，请重新登录'}, 401)
        except jwt.InvalidTokenError:
            return _json({'error': 'token无效'}, 401)
        try:
            request.user_profile = UserProfile.objects.get(id=payload['up_id'])
        except UserProfile.DoesNotExist:
            return _json({'error': '用户不存在'}, 401)
        return view_func(request, *args, **kwargs)
    return wrapper


def _make_token(profile, hours=168):
    payload = {
        'up_id': profile.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=hours),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


@csrf_exempt
@require_http_methods(['POST'])
def wx_login(request):
    try:
        body = json.loads(request.body)
        code = body.get('code', '').strip()
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    if not code:
        return _json({'error': 'code不能为空'}, 400)
    appid = getattr(settings, 'WX_APPID', '')
    secret = getattr(settings, 'WX_SECRET', '')
    if not appid or not secret:
        return _json({'error': '服务端未配置微信AppID/Secret'}, 500)
    url = (
        'https://api.weixin.qq.com/sns/jscode2session'
        f'?appid={appid}&secret={secret}&js_code={code}'
        '&grant_type=authorization_code'
    )
    try:
        with urllib_req.urlopen(url, timeout=10) as resp:
            wx_data = json.loads(resp.read().decode())
    except Exception as e:
        return _json({'error': f'微信接口调用失败: {e}'}, 502)
    if 'errcode' in wx_data and wx_data['errcode'] != 0:
        return _json({'error': wx_data.get('errmsg', '微信登录失败')}, 400)
    openid = wx_data.get('openid')
    if not openid:
        return _json({'error': '获取openid失败'}, 400)
    profile, _ = UserProfile.objects.get_or_create(openid=openid)
    token = _make_token(profile, hours=168)
    return _json({'token': token, 'display_name': profile.display_name})


@csrf_exempt
@require_http_methods(['POST'])
def web_login(request):
    try:
        body = json.loads(request.body)
        username = body.get('username', '').strip()
        password = body.get('password', '')
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    if not username or not password:
        return _json({'error': '用户名和密码不能为空'}, 400)
    user = authenticate(username=username, password=password)
    if user is None:
        return _json({'error': '用户名或密码错误'}, 401)
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={'display_name': user.get_full_name() or username},
    )
    token = _make_token(profile, hours=8)
    return _json({'token': token, 'username': username, 'display_name': profile.display_name})


@csrf_exempt
@require_http_methods(['GET', 'PUT'])
@jwt_required
def daily_report_detail(request, date):
    profile = request.user_profile
    try:
        report_date = datetime.date.fromisoformat(date)
    except ValueError:
        return _json({'error': '日期格式错误'}, 400)

    if request.method == 'GET':
        try:
            r = DailyReport.objects.get(user=profile, date=report_date)
            return _json({
                'date': date,
                'dept': r.dept, 'role': r.role, 'name': r.name,
                'blocks': r.blocks,
                'works': r.works, 'not_works': r.not_works,
                'plans': r.plans, 'commit': r.commit_text,
                'updated_at': r.updated_at.isoformat(),
            })
        except DailyReport.DoesNotExist:
            return _json({
                'date': date, 'dept': '', 'role': '', 'name': '',
                'blocks': [], 'works': '', 'not_works': '', 'plans': '',
                'commit': '--我承诺明天创造更高效的结果！', 'updated_at': None,
            })

    try:
        body = json.loads(request.body)
    except Exception:
        return _json({'error': '请求格式错误'}, 400)
    r, _ = DailyReport.objects.get_or_create(user=profile, date=report_date)
    r.dept = body.get('dept', '')
    r.role = body.get('role', '')
    r.name = body.get('name', '')
    r.blocks = body.get('blocks', [])
    r.works = body.get('works', '')
    r.not_works = body.get('not_works', '')
    r.plans = body.get('plans', '')
    r.commit_text = body.get('commit', '')
    r.save()
    return _json({'ok': True, 'updated_at': r.updated_at.isoformat()})


@csrf_exempt
@require_http_methods(['GET'])
@jwt_required
def daily_report_list(request):
    profile = request.user_profile
    year = request.GET.get('year')
    month = request.GET.get('month')
    if not year or not month:
        return _json({'error': '需要year和month参数'}, 400)
    try:
        year, month = int(year), int(month)
    except ValueError:
        return _json({'error': '参数格式错误'}, 400)
    dates = list(
        DailyReport.objects.filter(user=profile, date__year=year, date__month=month)
        .values_list('date', flat=True)
    )
    return _json({'dates': [d.isoformat() for d in dates]})


@csrf_exempt
@require_http_methods(['GET'])
@jwt_required
def weekly_analysis(request):
    profile = request.user_profile
    date_str = request.GET.get('date', datetime.date.today().isoformat())
    try:
        anchor = datetime.date.fromisoformat(date_str)
    except ValueError:
        return _json({'error': '日期格式错误'}, 400)
    monday = anchor - datetime.timedelta(days=anchor.weekday())
    sunday = monday + datetime.timedelta(days=6)
    reports = {r.date: r for r in DailyReport.objects.filter(
        user=profile, date__gte=monday, date__lte=sunday
    )}
    week_labels = ['一', '二', '三', '四', '五', '六', '日']
    days = []
    total_mins = 0
    total_done = 0
    for i in range(7):
        day = monday + datetime.timedelta(days=i)
        r = reports.get(day)
        day_mins = 0
        done_tasks = []
        if r:
            for blk in r.blocks:
                s, e = blk.get('start', ''), blk.get('end', '')
                if s and e:
                    try:
                        sh, sm = map(int, s.split(':'))
                        eh, em = map(int, e.split(':'))
                        mins = (eh * 60 + em) - (sh * 60 + sm)
                        if mins > 0:
                            day_mins += mins
                    except Exception:
                        pass
                for t in blk.get('tasks', []):
                    if t.get('progress', 0) >= 100 and t.get('desc', '').strip():
                        done_tasks.append(t['desc'].strip())
            total_mins += day_mins
            total_done += len(done_tasks)
        days.append({
            'date': day.isoformat(),
            'weekday': week_labels[i],
            'has_report': r is not None,
            'completed_tasks': done_tasks,
            'hours': round(day_mins / 60, 1),
        })
    return _json({
        'week_start': monday.isoformat(),
        'week_end': sunday.isoformat(),
        'days': days,
        'total_hours': round(total_mins / 60, 1),
        'completed_count': total_done,
    })

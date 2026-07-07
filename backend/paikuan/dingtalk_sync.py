"""钉钉审批同步 —— 取数分类、通用字段映射、同步/刷新落库，以及对外端点。

设计要点：
- "全部模板"口径：钉钉查询按模板(process_code)，逐模板拉某人的实例，再按任务分
  待处理/已处理/该员工发起。
- 模板五花八门（报销/付款/采购…字段各不同），故用"通用最佳努力映射"：
  审批编号=business_id、标题=title、申请人/部门取发起人或表单同名字段、
  金额取 MoneyField/含"金额"字段、收款方取常见关键字段，全表单原样存 ext_raw。
- 落库按 dingtalk_instance_id 去重：已存在→更新状态/金额，否则新建。
纯映射函数不碰网络，便于单测；端点只做参数校验 + 调 client + 落库。
"""
import datetime
import logging
import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from paikuan import dingtalk_client as dc
from paikuan.dingtalk_client import DingTalkError
from paikuan.models import ApprovalRecord
from paikuan.views import (DEPARTMENTS, err, get_request_perms, ok, parse_body,
                           pk_required)

logger = logging.getLogger(__name__)

# 通用字段匹配关键字（按优先级）
_PAYEE_KEYS = ['收款方', '收款单位', '收款账户', '收款账号', '收款人', '供应商名称', '供应商', '收款方名称']
_APPLICANT_KEYS = ['申请人', '创建人', '经办人']
_QUERY_CAP = 300   # 单次查询实例上限，超出提示缩小范围


# ── 通用映射 ──────────────────────────────────────────────────────────────────
def match_department(raw):
    """把钉钉部门串（如"劳务事业部-项目四部"）匹配到系统 7 大事业部之一；匹配不到留空。"""
    raw = raw or ''
    for d in DEPARTMENTS:
        if d in raw:
            return d
    return ''


def map_status(status, result):
    """钉钉审批状态 → 系统审批状态。"""
    status = (status or '').upper()
    result = (result or '').lower()
    if status == 'COMPLETED':
        return 'rejected' if result == 'refuse' else 'approved'
    if status in ('TERMINATED', 'CANCELED'):
        return 'canceled'
    return 'pending'   # NEW / RUNNING


def _num(value):
    """把 "1,455.50" / "600.00元" 之类抠成 Decimal，失败返回 None。"""
    if value is None:
        return None
    s = re.sub(r'[^0-9.\-]', '', str(value))
    if s in ('', '.', '-'):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _form_pairs(detail):
    """把 form_component_values 摊平成 [(name, value, comp_type)]（跳过空值）。"""
    out = []
    for it in (detail.get('form_component_values') or []):
        if not isinstance(it, dict):
            continue
        out.append((it.get('name', '') or '', it.get('value', ''), it.get('component_type', '') or ''))
    return out


def extract_amount(detail):
    """从表单抠总金额：优先"含总的金额字段"，否则所有 MoneyField/含"金额"字段取最大，否则 0。"""
    money = []
    for name, value, ctype in _form_pairs(detail):
        if ctype == 'MoneyField' or '金额' in name:
            n = _num(value)
            if n is not None:
                money.append((name, n))
    if not money:
        return Decimal('0')
    totals = [n for name, n in money if '总' in name]
    if totals:
        return max(totals)
    return max(n for _, n in money)


def extract_payee(detail, applicant):
    """收款方：按常见关键字段取；取不到回退为申请人（报销单收款方即本人）。"""
    pairs = _form_pairs(detail)
    for key in _PAYEE_KEYS:
        for name, value, _ in pairs:
            if key in name and str(value).strip():
                return str(value).strip()[:200]
    return (applicant or '')[:200]


def _form_field(detail, keys):
    for key in keys:
        for name, value, _ in _form_pairs(detail):
            if key in name and str(value).strip():
                return str(value).strip()
    return ''


def instance_to_fields(detail, name_resolver=None):
    """钉钉实例详情 → ApprovalRecord 字段 dict（通用最佳努力）。
    name_resolver(userid)->name 可选，仅在表单无"申请人"字段时用来解发起人姓名。"""
    applicant = _form_field(detail, _APPLICANT_KEYS)
    if not applicant:
        uid = detail.get('originator_userid') or ''
        applicant = (name_resolver(uid) if (name_resolver and uid) else uid) or ''
    dept_raw = (detail.get('originator_dept_name') or _form_field(detail, ['部门']) or '')
    number = (detail.get('business_id') or '')[:21]
    title = (detail.get('title') or '').strip() or '钉钉审批'
    return {
        'applicant': applicant[:100] or '—',
        'department': match_department(dept_raw) or '集团总部',
        'approval_number': number,
        'summary': title[:500],
        'amount': extract_amount(detail),
        'payee': extract_payee(detail, applicant) or '—',
        'status': map_status(detail.get('status'), detail.get('result')),
        'secondary_dept': dept_raw[:100],
        'ext_source': 'dingtalk',
        'dingtalk_instance_id': detail.get('_instance_id') or detail.get('business_id') or '',
        'ext_raw': {'title': title, 'business_id': number, 'dept': dept_raw,
                    'status': detail.get('status'), 'result': detail.get('result'),
                    'form': [{'name': n, 'value': v} for n, v, _ in _form_pairs(detail)]},
    }


def classify(detail, userid):
    """该 userid 在这条审批里的角色：todo(待他处理) / done(已处理) / originated(他发起)。"""
    tasks = [t for t in (detail.get('tasks') or []) if t.get('userid') == userid]
    if any((t.get('task_status') or '').upper() in ('RUNNING', 'NEW', 'PENDING') for t in tasks):
        return 'todo'
    if tasks:   # 有任务且都非进行中 = 已处理
        return 'done'
    if detail.get('originator_userid') == userid:
        return 'originated'
    return 'other'


# ── 端点 ──────────────────────────────────────────────────────────────────────
def _page_denied(request):
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('approval_records', True):
        return err('无访问权限', 403, 403)
    return None


def _write_denied(request):
    perms = get_request_perms(request)
    if perms is not None:
        if not perms['pages'].get('approval_records', True):
            return err('无访问权限', 403, 403)
        if not perms.get('can_create', True):
            return err('无创建权限', 403, 403)
    return None


def _ms(date_str, end=False):
    d = datetime.date.fromisoformat(date_str)
    t = datetime.time(23, 59, 59) if end else datetime.time(0, 0, 0)
    dt = timezone.make_aware(datetime.datetime.combine(d, t))
    return int(dt.timestamp() * 1000)


@csrf_exempt
@pk_required()
def dingtalk_test(request):
    """GET 测试钉钉连通性并列出可同步的审批模板（供配置核对）。"""
    denied = _page_denied(request)
    if denied:
        return denied
    try:
        dc.access_token()
        templates = dc.list_process_codes()
    except DingTalkError as ex:
        return err(str(ex), 502, 502)
    return ok({'connected': True, 'templates': templates,
               'note': '未列出模板时，请在环境变量 DINGTALK_PROCESS_CODES 配置要同步的模板 process_code'})


@csrf_exempt
@pk_required()
def dingtalk_resolve_user(request):
    """POST {mobile} 或 {name} → 候选人列表（手机号唯一；姓名可能多个，交前端选择）。"""
    denied = _page_denied(request)
    if denied:
        return denied
    body = parse_body(request)
    mobile = (body.get('mobile') or '').strip()
    name = (body.get('name') or '').strip()
    try:
        if mobile:
            uid = dc.userid_by_mobile(mobile)
            if not uid:
                return ok({'users': []})
            info = dc.user_detail(uid)
            return ok({'users': [{'userid': uid, 'name': info.get('name') or mobile}]})
        if name:
            return ok({'users': dc.users_by_name(name)})
    except DingTalkError as ex:
        return err(str(ex), 502, 502)
    return err('请提供手机号或姓名')


@csrf_exempt
@pk_required()
def dingtalk_query(request):
    """POST {userid, start, end, status:todo|done|originated} →
    该员工在时间区间内、跨全部模板的审批列表（含系统同步状态）。"""
    denied = _page_denied(request)
    if denied:
        return denied
    body = parse_body(request)
    userid = (body.get('userid') or '').strip()
    status = (body.get('status') or 'todo').strip()
    if not userid:
        return err('缺少 userid')
    if status not in ('todo', 'done', 'originated'):
        return err('status 无效（todo/done/originated）')
    try:
        start_ms, end_ms = _ms(body['start']), _ms(body['end'], end=True)
    except Exception:
        return err('时间范围无效（YYYY-MM-DD）')

    try:
        templates = dc.list_process_codes()
        if not templates:
            return err('未配置任何审批模板（DINGTALK_PROCESS_CODES 为空且无法枚举），无法查询', 400)
        name_by_code = {t['process_code']: t.get('name', '') for t in templates}
        inst_ids = []
        for t in templates:
            for iid in dc.list_instance_ids(t['process_code'], start_ms, end_ms, userid):
                inst_ids.append((iid, t['process_code']))
                if len(inst_ids) > _QUERY_CAP:
                    break
            if len(inst_ids) > _QUERY_CAP:
                break
        capped = len(inst_ids) > _QUERY_CAP
        inst_ids = inst_ids[:_QUERY_CAP]

        # 已同步集合（一次查库）
        synced = {r.dingtalk_instance_id: r for r in ApprovalRecord.objects.filter(
            dingtalk_instance_id__in=[i for i, _ in inst_ids], deleted_at__isnull=True)}

        items = []
        for iid, code in inst_ids:
            detail = dc.get_instance(iid)
            role = classify(detail, userid)
            if role != status:
                continue
            f = instance_to_fields(detail)
            rec = synced.get(iid)
            sys_status = map_status(detail.get('status'), detail.get('result'))
            items.append({
                'instance_id': iid,
                'template': name_by_code.get(code, code),
                'title': f['summary'],
                'approval_number': f['approval_number'],
                'applicant': f['applicant'],
                'department': f['department'],
                'amount': str(f['amount']),
                'payee': f['payee'],
                'ding_status': sys_status,
                'task': role,
                'create_time': detail.get('create_time', ''),
                'synced': bool(rec),
                'sync_rec_no': rec.approval_number if rec else '',
                'sync_stale': bool(rec) and rec.status != sys_status,
            })
    except DingTalkError as ex:
        return err(str(ex), 502, 502)

    items.sort(key=lambda x: x['create_time'], reverse=True)
    return ok({'items': items, 'count': len(items), 'capped': capped})


def _upsert(detail, actor):
    """按 dingtalk_instance_id 落库：存在则更新，否则新建。返回 ('created'|'updated', rec)。"""
    f = instance_to_fields(detail)
    iid = f['dingtalk_instance_id']
    rec = ApprovalRecord.objects.filter(dingtalk_instance_id=iid, deleted_at__isnull=True).first()
    if rec:
        rec.status = f['status']
        rec.amount = f['amount']
        rec.summary = f['summary']
        rec.payee = f['payee']
        rec.ext_raw = f['ext_raw']
        rec.save(update_fields=['status', 'amount', 'summary', 'payee', 'ext_raw', 'updated_at'])
        return 'updated', rec
    rec = ApprovalRecord.objects.create(created_by=actor, **f)
    return 'created', rec


@csrf_exempt
@pk_required()
def dingtalk_sync(request):
    """POST {instance_ids:[...]} → 把所选钉钉审批同步进审批管理（按实例ID去重）。"""
    denied = _write_denied(request)
    if denied:
        return denied
    body = parse_body(request)
    ids = body.get('instance_ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请提供要同步的 instance_ids')
    if len(ids) > 200:
        return err('单次同步上限 200 条，请缩小选择范围')
    actor = getattr(request, 'pk_user', None)
    created, updated, skipped = 0, 0, []
    try:
        for iid in ids:
            detail = dc.get_instance(iid)
            try:
                kind, _ = _upsert(detail, actor)
                created += (kind == 'created')
                updated += (kind == 'updated')
            except Exception as ex:   # 单条落库失败不影响整体
                logger.error('dingtalk sync upsert failed %s: %s', iid, ex)
                skipped.append({'id': iid, 'reason': str(ex)[:120]})
    except DingTalkError as ex:
        return err(str(ex), 502, 502)
    return ok({'created': created, 'updated': updated, 'skipped': skipped,
               'message': f'新建 {created} 条、更新 {updated} 条'
                          + (f'、跳过 {len(skipped)} 条' if skipped else '')})


@csrf_exempt
@pk_required()
def dingtalk_refresh(request):
    """POST {instance_ids:[...]} → 对已同步记录重新拉取钉钉最新状态并回写。"""
    denied = _write_denied(request)
    if denied:
        return denied
    body = parse_body(request)
    ids = body.get('instance_ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请提供要刷新的 instance_ids')
    if len(ids) > 200:
        return err('单次刷新上限 200 条')
    updated, skipped = 0, []
    try:
        recs = {r.dingtalk_instance_id: r for r in ApprovalRecord.objects.filter(
            dingtalk_instance_id__in=ids, deleted_at__isnull=True)}
        for iid in ids:
            rec = recs.get(iid)
            if not rec:
                skipped.append({'id': iid, 'reason': '系统内无该同步记录'})
                continue
            detail = dc.get_instance(iid)
            new_status = map_status(detail.get('status'), detail.get('result'))
            new_amount = extract_amount(detail)
            if rec.status != new_status or rec.amount != new_amount:
                rec.status, rec.amount = new_status, new_amount
                rec.save(update_fields=['status', 'amount', 'updated_at'])
                updated += 1
    except DingTalkError as ex:
        return err(str(ex), 502, 502)
    return ok({'updated': updated, 'skipped': skipped,
               'message': f'刷新更新 {updated} 条' + (f'、跳过 {len(skipped)} 条' if skipped else '')})

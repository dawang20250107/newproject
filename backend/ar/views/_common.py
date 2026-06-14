import io
import json
import logging
import re
import datetime
import calendar
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

logger = logging.getLogger(__name__)

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Sum, Count, Q, F, Value, Case, When, IntegerField, CharField, DecimalField, Max, Min
from django.db.models.functions import TruncMonth, Coalesce
from django.utils import timezone

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from paikuan.views import (pk_required, ok, err, DEPARTMENTS, VALID_DEPARTMENTS,
                           get_request_perms, apply_ar_view_mask, AR_PROJECT_FIELD_DEFS,
                           AR_RECORD_FIELD_DEFS, AR_ADVANCE_FIELD_DEFS, _paid_subq)
from ar.models import (ARProject, ARRecord, ARPayment, ARAdjustment,
                       BatchInvoiceEvent,
                       CollectionBudget, PaymentBudget,
                       AdvanceRecord, AdvanceWriteoff, AdvanceInstallment,
                       Supplier, Customer,
                       Contract, ContractParty, ContractProject, ActionItem,
                       CashPoolConfig, CashPoolTransfer)
from paikuan.models import Payment, PaymentInstallment, ApprovalRecord

# ── AR page keys (must match PAGE_KEYS in paikuan/views.py) ───────────────────
AR_PAGE_KEYS = ['ar_projects', 'ar_records', 'ar_advance', 'ar_analytics', 'ar_cashflow', 'ar_budget']

ADVANCE_DIRECTIONS = ['预收', '预付']

EXAMPLE_ROW_MARKER = '示例-导入前请删除此行'
VALID_CUSTOMER_LEVELS = ['S级', 'A级', 'B级', 'C级', 'D级']
VALID_INVOICE_TYPES = ['专票', '普票', '不开票']


def _norm_header(h):
    """规范化 Excel 表头：去空格、去必填星号、去括号注释，使模板(带*)与
    导出(不带*)的表头可双向匹配。例：'合同名称*'、'开票模式(全额/差额)' →
    '合同名称'、'开票模式'。"""
    s = str(h or '').strip().replace('＊', '').replace('*', '')
    s = s.replace('（', '(').replace('）', ')')
    s = re.sub(r'\([^)]*\)', '', s)   # 去掉括号及其中的注释
    return s.strip()


def _parse_cycle_start_day(v):
    """对账周期起始日：1~28（1=自然月）。返回 (值, 错误文案)。空值按 1。"""
    if v in (None, ''):
        return 1, None
    try:
        d = int(float(v))
    except (TypeError, ValueError):
        return None, f'对账周期起始日"{v}"无效，须为 1~28 的整数（1=自然月）'
    if not (1 <= d <= 28):
        return None, f'对账周期起始日须为 1~28（当前 {d}）。29~31 在短月不存在，请用 28 或改约对账日'
    return d, None


def _match_project_by_short_name(short_name, dept='', allowed_depts=None):
    """Simple lookup used by non-import paths (project search, etc.)."""
    name = (short_name or '').strip()
    if not name:
        return None
    qs = ARProject.objects.filter(short_name=name)
    if dept:
        qs = qs.filter(delivery_dept=dept)
    elif allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    proj = qs.order_by('-id').first()
    if proj:
        return proj
    qs = ARProject.objects.filter(short_name__icontains=name)
    if dept:
        qs = qs.filter(delivery_dept=dept)
    elif allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    return qs.order_by('-id').first()


def _proj_candidate_dict(p):
    """歧义候选项的精简信息，供导入返回让用户挑选/区分。"""
    return {
        'project_no': p.project_no,
        'short_name': p.short_name,
        'customer_name': p.customer_name,
        'delivery_dept': p.delivery_dept,
    }


def _classify_project_for_import(short_name, customer_hint, project_no, allowed_depts, dept_hint=''):
    """只读判定项目归属（不建库、不创建草稿），用于导入前的歧义检查。

    返回 (status, payload)：
      'resolved'  -> payload = ARProject（唯一命中）
      'ambiguous' -> payload = 候选 list[dict]（多命中且无法区分，需人工指定）
      'bad_no'    -> payload = 填写的项目编号（填了但查不到/越权）
      'not_found' -> payload = None（找不到，写入阶段将自动建草稿）

    优先级：项目编号(确定性) > 精确简称(+客户名缩小) > 模糊简称(+客户名缩小)。
    """
    name = (short_name or '').strip()
    pno = (project_no or '').strip()
    dh = (dept_hint or '').strip()

    # ── 0) 项目编号：最高优先级、确定性指定 ────────────────────────────────
    if pno:
        qs = ARProject.objects.filter(project_no=pno)
        if allowed_depts is not None:
            qs = qs.filter(delivery_dept__in=allowed_depts)
        proj = qs.first()
        return ('resolved', proj) if proj else ('bad_no', pno)

    def _narrow(qs):
        # 交付部门是业务主键的一部分（短名+部门），优先用它区分同名跨部门项目
        if dh:
            nd = qs.filter(delivery_dept=dh)
            if nd.exists():
                qs = nd
        if customer_hint:
            n = qs.filter(customer_name__icontains=customer_hint)
            if n.exists():
                return n
        return qs

    # ── 1) 精确简称 ────────────────────────────────────────────────────────
    qs = ARProject.objects.filter(short_name=name)
    if allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    qs = _narrow(qs)
    cnt = qs.count()
    if cnt == 1:
        return 'resolved', qs.first()
    if cnt > 1:
        return 'ambiguous', [_proj_candidate_dict(p) for p in qs.order_by('-id')[:8]]

    # ── 2) 模糊简称 ────────────────────────────────────────────────────────
    qs2 = ARProject.objects.filter(short_name__icontains=name)
    if allowed_depts is not None:
        qs2 = qs2.filter(delivery_dept__in=allowed_depts)
    qs2 = _narrow(qs2)
    cnt2 = qs2.count()
    if cnt2 == 1:
        return 'resolved', qs2.first()
    if cnt2 > 1:
        return 'ambiguous', [_proj_candidate_dict(p) for p in qs2.order_by('-id')[:8]]

    # ── 3) 找不到 → 写入阶段自动建草稿 ─────────────────────────────────────
    return 'not_found', None


def _resolve_project_for_import(short_name, customer_hint, dept, allowed_depts, user,
                                proj_cache, project_no=''):
    """3-stage project resolution for bulk import.

    Returns (proj, match_type, warning_str | None).
    match_type: 'exact' | 'exact_multi' | 'fuzzy' | 'fuzzy_multi' | 'created'

    Uses proj_cache {(short_name, dept) -> result} to avoid creating duplicate
    draft projects when multiple rows share the same project name.
    若提供 project_no（项目编号），优先按编号精确命中，作为确定性指定。
    """
    name = (short_name or '').strip()
    if not name:
        return None, None, None
    cache_key = (name, dept or '')

    # 项目编号确定性命中（不进 proj_cache，按编号逐行解析）
    pno = (project_no or '').strip()
    if pno:
        qs_no = ARProject.objects.filter(project_no=pno)
        if allowed_depts is not None:
            qs_no = qs_no.filter(delivery_dept__in=allowed_depts)
        proj_no = qs_no.first()
        if proj_no:
            return proj_no, 'exact', None

    if cache_key in proj_cache:
        return proj_cache[cache_key]

    # ── Stage 1: 精确匹配 ──────────────────────────────────────────────────
    qs = ARProject.objects.filter(short_name=name)
    if allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    # 交付部门是业务主键的一部分：用它区分同名跨部门项目（在权限范围内进一步缩小）
    if dept:
        qs_dept = qs.filter(delivery_dept=dept)
        if qs_dept.exists():
            qs = qs_dept

    # Customer hint可进一步缩小范围（同名项目不同客户时）
    if customer_hint:
        qs_cust = qs.filter(customer_name__icontains=customer_hint)
        if qs_cust.exists():
            cnt = qs_cust.count()
            proj = qs_cust.order_by('-id').first()
            warn = (f'找到 {cnt} 个同名同客户项目，已取最新的「{proj.customer_name}」，请核查'
                    if cnt > 1 else None)
            result = (proj, 'exact' if cnt == 1 else 'exact_multi', warn)
            proj_cache[cache_key] = result
            return result

    if qs.exists():
        cnt = qs.count()
        proj = qs.order_by('-id').first()
        warn = (f'找到 {cnt} 个同名项目，已取最新的「{proj.customer_name}」，请核查'
                if cnt > 1 else None)
        result = (proj, 'exact' if cnt == 1 else 'exact_multi', warn)
        proj_cache[cache_key] = result
        return result

    # ── Stage 2: 模糊匹配（contains）──────────────────────────────────────
    qs2 = ARProject.objects.filter(short_name__icontains=name)
    if allowed_depts is not None:
        qs2 = qs2.filter(delivery_dept__in=allowed_depts)
    if dept:
        qs2_dept = qs2.filter(delivery_dept=dept)
        if qs2_dept.exists():
            qs2 = qs2_dept
    matches = list(qs2.order_by('-id')[:5])
    if matches:
        proj = matches[0]
        if len(matches) > 1:
            candidates = '、'.join(f'「{m.short_name}」' for m in matches[:3])
            warn = f'"{name}"模糊匹配到多个项目（{candidates}），已取最新的「{proj.short_name}」，建议核查'
            match_type = 'fuzzy_multi'
        else:
            warn = f'"{name}"未精确匹配，模糊命中「{proj.short_name}」，建议核查'
            match_type = 'fuzzy'
        result = (proj, match_type, warn)
        proj_cache[cache_key] = result
        return result

    # ── Stage 3: 自动创建草稿项目 ─────────────────────────────────────────
    proj_dept = dept or (list(allowed_depts)[0] if allowed_depts else '')
    creator_name = user.name if user else '待填'
    proj = ARProject(
        short_name=name,
        customer_name=customer_hint or name,
        delivery_dept=proj_dept,
        is_draft=True,
        sales_contact=creator_name,
        project_manager=creator_name,
        has_contract='无',
    )
    proj.save()
    warn = f'项目台账中未找到「{name}」，已自动创建草稿项目，请到项目台账补充完善'
    result = (proj, 'created', warn)
    proj_cache[cache_key] = result
    return result


def _normalize_date(s):
    """Best-effort normalize a user-typed date string to ISO YYYY-MM-DD.

    Accepts: 2026-01-15, 2026/1/15, 2026.1.15, 2026年1月15日, 26/1/15,
    20260115, datetime/date objects, Excel serial numbers.
    """
    import datetime as _dt
    if s is None:
        return None
    # datetime / date objects (openpyxl can return these)
    if isinstance(s, (_dt.datetime, _dt.date)):
        return s.strftime('%Y-%m-%d')
    # Excel serial date (number of days since 1899-12-30)
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        try:
            base = _dt.date(1899, 12, 30)
            return (base + _dt.timedelta(days=int(s))).strftime('%Y-%m-%d')
        except (OverflowError, ValueError):
            return None
    s = str(s).strip()
    if not s or s.lower() == 'none':
        return None
    # 20260115 → 2026-01-15
    if re.fullmatch(r'\d{8}', s):
        try:
            return f'{s[:4]}-{s[4:6]}-{s[6:]}'
        except ValueError:
            pass
    # Drop chinese unit suffixes / unify separators
    cleaned = (s.replace('/', '-').replace('.', '-')
                .replace('年', '-').replace('月', '-').replace('日', '')
                .replace(' ', '').strip('-'))
    parts = [p for p in cleaned.split('-') if p]
    try:
        if len(parts) >= 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            # 2-digit year → 20xx
            if y < 100:
                y += 2000
            _dt.date(y, m, d)  # validate
            return f'{y:04d}-{m:02d}-{d:02d}'
    except (ValueError, TypeError):
        pass
    return None


def _dec(v, default=Decimal('0')):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return default


def _int_param(request, key, default):
    """GET 参数安全转 int：非法值回退默认值（避免 ?year=abc 之类把接口打成500）。"""
    try:
        return int(request.GET.get(key, default) or default)
    except (ValueError, TypeError):
        return int(default)


def _parse_body(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _ar_dept_filter(qs, request, dept_field='delivery_dept', shared_field=None):
    """Filter queryset by the requesting user's allowed departments.
    Optional ?depts=A,B,C further narrows the set (intersected with pk_depts).
    When shared_field is provided and the user has ar_shared_only, restricts to
    shared projects only (shared_field=True)."""
    raw = request.GET.get('depts', '').strip()
    requested = [d for d in raw.split(',') if d.strip()] if raw else []

    if request.pk_role == 'super_admin':
        if requested:
            qs = qs.filter(**{f'{dept_field}__in': requested})
        return qs

    allowed = set(request.pk_depts or [])
    if not allowed:
        return qs.none()
    if requested:
        active = [d for d in requested if d in allowed]
        if active:
            qs = qs.filter(**{f'{dept_field}__in': active})
        else:
            qs = qs.filter(**{f'{dept_field}__in': request.pk_depts})
    else:
        qs = qs.filter(**{f'{dept_field}__in': request.pk_depts})

    if shared_field:
        from paikuan.views import get_request_perms
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only'):
            qs = qs.filter(**{shared_field: True})
    return qs


def _page_denied(request, page_key):
    """Return error response if user lacks access to a page; None if allowed."""
    if request.pk_role == 'super_admin':
        return None
    from paikuan.views import get_job_perms
    jt = getattr(request, 'pk_job', '') or ''
    if not jt:
        from paikuan.models import PaikuanUser
        u = PaikuanUser.objects.filter(id=request.pk_uid).only('job_title').first()
        jt = u.job_title if u else ''
    perms = get_job_perms(jt)
    if not perms['pages'].get(page_key, True):
        return err('无权访问此模块', 403)
    return None


def _write_denied(request):
    perms = get_request_perms(request)
    # AR 写入：优先看 ar_can_create（结算会计等聚焦应收的岗位），回退到通用 can_create。
    if perms is not None and not (perms.get('ar_can_create') or perms.get('can_create', False)):
        return err('无写入权限', 403, 403)
    return None


def _action_denied(request, action_key):
    """操作级权限：核销/回款录入等细粒度动作的独立开关。

    actions[key] 显式配置时以其为准（True 放行 / False 拒绝）；
    旧配置无 actions 键时回退通用写权限（向后兼容，不会突然把人锁外面）。
    出纳等岗位可借此单独获得「预付核销」而不必放开整个 can_create。"""
    perms = get_request_perms(request)
    if perms is None:
        return None
    acts = perms.get('actions')
    if isinstance(acts, dict) and action_key in acts:
        if acts.get(action_key):
            return None
        return err('当前职务未开通此操作权限，请联系管理员在「权限配置·操作权限」中开通', 403, 403)
    return _write_denied(request)


def _delete_denied(request):
    perms = get_request_perms(request)
    if perms is not None and not perms.get('can_delete', False):
        return err('无删除权限', 403, 403)
    return None


def _dept_denied(request, dept, msg='无权操作此部门'):
    if request.pk_role == 'super_admin':
        return None
    if dept not in request.pk_depts:
        return err(msg, 403, 403)
    return None


def _sync_project_contracts(proj, contract_ids, request):
    """替换某项目挂靠的合同（项目侧维护多对多）。只挂用户有权部门的合同。"""
    proj.contract_links.all().delete()
    seen = set()
    for cid in (contract_ids or []):
        try:
            cid = int(cid)
        except (ValueError, TypeError):
            continue
        if cid in seen:
            continue
        ct = Contract.objects.filter(pk=cid).first()
        if not ct:
            continue
        if (request.pk_role != 'super_admin' and ct.delivery_dept
                and ct.delivery_dept not in request.pk_depts):
            continue
        seen.add(cid)
        ContractProject.objects.create(contract=ct, project=proj, is_primary=True)


def _project_contracts_list(proj):
    return [
        {'contract_id': cp.contract_id, 'name': cp.contract.name,
         'contract_no': cp.contract.contract_no, 'is_primary': cp.is_primary}
        for cp in proj.contract_links.select_related('contract').all()
    ]


def _object_dept_denied(request, obj, dept_field='delivery_dept'):
    return _dept_denied(request, getattr(obj, dept_field, ''), '无权访问')


def _can_ar_view(request, field_key):
    perms = get_request_perms(request)
    if perms is None:
        return True
    return (perms.get('ar_view') or {}).get(field_key, True)


def _ar_field_denied(request, field_key):
    if not _can_ar_view(request, field_key):
        return err('无权访问此字段', 403, 403)
    return None


_AR_PAYLOAD_DEFS_BY_GROUP = {
    'project': AR_PROJECT_FIELD_DEFS,
    'record': AR_RECORD_FIELD_DEFS,
    'advance': AR_ADVANCE_FIELD_DEFS,
}


def _ar_visible_payload(request, data, group, extra=()):
    perms = get_request_perms(request)
    if perms is None:
        return data
    defs = _AR_PAYLOAD_DEFS_BY_GROUP.get(group, AR_RECORD_FIELD_DEFS)
    ar_view = perms.get('ar_view') or {}
    cols = set(extra)
    for f in defs:
        if ar_view.get(f['key'], True):
            cols.update(f['cols'])
    return {k: v for k, v in data.items() if k in cols}


def _visible_ar_export_cols(request, columns):
    perms = get_request_perms(request)
    if perms is None:
        return columns
    ar_view = perms.get('ar_view') or {}
    return [col for col in columns if col[0] is None or ar_view.get(col[0], True)]


_XL_FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')


def _export_response(wb, filename):
    # Excel 公式注入防护（与排款导出口径一致）：全部工作表的文本单元格，
    # 以 =+-@ 等开头的前置单引号转义。集中在导出总出口做，覆盖所有 AR 导出。
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v and v[0] in _XL_FORMULA_CHARS:
                    cell.value = "'" + v
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(buf.read(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    safe = quote(filename, safe='')
    resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe}"
    resp['Cache-Control'] = 'no-store'
    return resp


def _header_row(ws, headers, color='1565C0'):
    fill = PatternFill('solid', fgColor=color)
    font = Font(color='FFFFFF', bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal='center')


# 自动汇总本模块所有公开名（含单下划线助手）供各业务域 `from ._common import *`：
# dir() 在模块末尾返回当前命名空间全部名称；排除 dunder 即得到需要再导出的集合。
__all__ = [n for n in dir() if not n.startswith('__')]

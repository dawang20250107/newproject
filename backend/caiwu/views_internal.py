"""内部往来核对（金蝶云星空补位模块）。

数据源（金蝶导出，两种文件自动识别，均支持全集团多账簿一次性导出）：
1. 明细分类账（总账→明细分类账，核算维度=组织机构）→ 两两明细比对的数据源。
   按「账簿」列自动拆分记账主体、按「记账日期/期间」自动拆分期间。
2. 核算维度余额表（总账→核算维度余额表）→ 差异矩阵的首选口径：
   期末余额镜像核对含期初遗留差异，仅有明细时矩阵退化为本期发生口径。

核对逻辑（镜像原则）：A 主体账上「对 B 的应收」（资产类，借增）必对应
B 主体账上「对 A 的应付」（负债类，贷增）。每行/每余额 signed=借-贷
（债权为正），A 对 B 与 B 对 A 的 signed 之和即镜像差异。
"""
import datetime
import json
import logging
import re
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

from django.db import transaction
from django.db.models import F, Sum
from django.views.decorators.csrf import csrf_exempt

from .models import (
    InternalBalance, InternalBatch, InternalEntry,
    BUSINESS_UNITS, VALID_BUSINESS_UNITS,
)
from .views import (
    cw_required, ok, err, _page_denied, _can_upload, _can_delete,
    _can_access_bu, IMPORT_SIZE_LIMIT, _load_ws_any,
)

# 集团主体公司全称 ↔ 事业部（用户提供的对应关系）。
# 账簿名（如「卡行通集团主账簿」）与核算维度原文（如「组织机构:四川阔展物流有限公司」）
# 都经此映射；先精确公司名，再词干兜底。
_COMPANY_BU = {
    '卡行通集团': '集团总部',
    '四川迭黎信息技术有限公司': '劳务事业部',
    '四川阔展物流有限公司': '阔展事业部',
    '成都宁创物流有限公司': '供应链事业部',
    '四川卡行通供应链管理有限公司': '运输事业部',
    '四川金聚源运业有限公司': '自营事业部',
    '成都杨山物流有限公司': '多式联运事业部',
}
# 词干兜底（更长/更特异在前；「多式联运」不含「运输」二字序列，互不误伤）
_CP_STEMS = [
    ('迭黎', '劳务事业部'),
    ('阔展', '阔展事业部'),
    ('宁创', '供应链事业部'),
    ('金聚源', '自营事业部'),
    ('杨山', '多式联运事业部'),
    ('卡行通供应链', '运输事业部'),
    ('多式联运', '多式联运事业部'),
    ('供应链', '供应链事业部'),
    ('劳务', '劳务事业部'),
    ('运输', '运输事业部'),
    ('自营', '自营事业部'),
    ('总部', '集团总部'),
    ('卡行通集团', '集团总部'),
]

# 金蝶明细/余额表里的小计汇总摘要（非业务发生行）
_SKIP_SUMMARIES = {'期初余额', '本期合计', '本年累计', '本月合计', '本期发生', '累计', '合计', '期末余额'}


def _map_entity(raw):
    """公司全称/账簿名/维度原文 → 事业部；识别不了返回 ''。"""
    s = (raw or '').strip()
    if not s:
        return ''
    # 组合维度串（如「组织机构:四川阔展物流有限公司」）取冒号后值
    if ':' in s or '：' in s:
        s = s.replace('：', ':').split(':')[-1].strip()
    s = re.sub(r'主?账簿$', '', s).strip()
    if s in VALID_BUSINESS_UNITS:
        return s
    if s in _COMPANY_BU:
        return _COMPANY_BU[s]
    for name, bu in _COMPANY_BU.items():
        if name in s:
            return bu
    for stem, bu in _CP_STEMS:
        if stem in s:
            return bu
    return ''


def _cell_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v or '').strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日', '%Y.%m.%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cell_dec(v):
    try:
        s = str(v if v is not None else 0).replace(',', '').strip() or '0'
        return Decimal(s)
    except (InvalidOperation, TypeError):
        return Decimal('0')


def _period_of(date_v, period_str):
    """行期间：优先记账日期；否则解析「2026年5期」。返回 (year, month) 或 None。"""
    if date_v:
        return date_v.year, date_v.month
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*期', str(period_str or ''))
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


# ── 明细分类账解析 ────────────────────────────────────────────────────────────

def _detect_detail_ledger(ws):
    """识别金蝶「明细分类账」（含旧版核算维度明细账）。
    必需：维度列（核算维度/往来单位…）、摘要、借方、贷方；
    可选：账簿、期间、记账日期/业务日期/日期、凭证字号、（左树）科目编码/名称。
    返回 (data_start, col_map) 或 (None, {})。金蝶两行复合表头时主行即含必需列，
    次行（方向/金额）无金额被行级过滤跳过。"""
    dim_names = ('核算维度', '往来单位', '内部往来单位', '往来单位名称', '内部单位', '往来组织', '组织机构')
    for ri in range(1, min(12, ws.max_row + 1)):
        cm = {}
        for ci in range(1, min(ws.max_column + 1, 40)):
            v = str(ws.cell(row=ri, column=ci).value or '').strip()
            if not v:
                continue
            if v in dim_names or any(v.startswith(d) for d in dim_names):
                cm.setdefault('cp', ci)
            elif v == '摘要':
                cm['summary'] = ci
            elif v in ('借方', '借方金额'):
                cm['debit'] = ci
            elif v in ('贷方', '贷方金额'):
                cm['credit'] = ci
            elif v in ('记账日期', '业务日期', '日期'):
                cm.setdefault('date', ci)
            elif v == '期间':
                cm['period'] = ci
            elif v in ('凭证字号', '凭证号'):
                cm['voucher'] = ci
            elif v in ('科目编码', '左树科目编码'):
                cm['code'] = ci
            elif v in ('科目名称', '左树科目名称'):
                cm['name'] = ci
            elif v in ('账簿', '账簿名称'):
                cm['book'] = ci
        if all(k in cm for k in ('cp', 'summary', 'debit', 'credit')):
            return ri + 1, cm
    return None, {}


def _parse_detail(ws, data_start, cm, bu_param, form_period):
    """→ (entries, unmatched{原文:次数}, self_ref{原文:次数}, skipped, errors[])
    unmatched=对方主体无法识别为集团内主体（按外部往来处理）；
    self_ref=对方主体经识别后与记账主体本身相同（本主体自身的往来，自动跳过、不参与核对）。"""
    entries, unmatched, self_ref, skipped, errors = [], {}, {}, 0, []
    unknown_books = {}
    for ri in range(data_start, ws.max_row + 1):
        summ = str(ws.cell(row=ri, column=cm['summary']).value or '').strip()
        if summ in _SKIP_SUMMARIES or '结转' in summ:
            skipped += 1
            continue
        debit = _cell_dec(ws.cell(row=ri, column=cm['debit']).value)
        credit = _cell_dec(ws.cell(row=ri, column=cm['credit']).value)
        if not debit and not credit:
            skipped += 1
            continue
        # 记账主体：账簿列优先，无账簿列时用上传参数
        if 'book' in cm:
            book_raw = str(ws.cell(row=ri, column=cm['book']).value or '').strip()
            bu = _map_entity(book_raw) or bu_param
            if not bu:
                unknown_books[book_raw or '（空）'] = unknown_books.get(book_raw or '（空）', 0) + 1
                skipped += 1
                continue
        else:
            bu = bu_param
            if not bu:
                errors.append('文件无「账簿」列，请在上传时选择记账主体')
                return [], {}, {}, 0, errors
        # 期间：记账日期 → 期间列 → 上传参数
        d = _cell_date(ws.cell(row=ri, column=cm['date']).value) if 'date' in cm else None
        ym = _period_of(d, ws.cell(row=ri, column=cm['period']).value if 'period' in cm else '')
        ym = ym or form_period
        if not ym:
            skipped += 1
            continue
        raw_cp = str(ws.cell(row=ri, column=cm['cp']).value or '').strip()
        cp = _map_entity(raw_cp)
        if cp == bu:
            # 本主体自身的往来（对方=记账主体），非「未识别」——单列自动跳过、不参与核对
            self_ref[raw_cp or '（空）'] = self_ref.get(raw_cp or '（空）', 0) + 1
            skipped += 1
            continue
        if not cp:
            unmatched[raw_cp or '（空）'] = unmatched.get(raw_cp or '（空）', 0) + 1
        code = str(ws.cell(row=ri, column=cm['code']).value or '').strip() if 'code' in cm else ''
        entries.append(InternalEntry(
            business_unit=bu, counterparty=cp, counterparty_raw=raw_cp[:200],
            year=ym[0], month=ym[1], biz_date=d,
            voucher_no=str(ws.cell(row=ri, column=cm['voucher']).value or '').strip()[:64] if 'voucher' in cm else '',
            subject_code=code[:32],
            subject_name=str(ws.cell(row=ri, column=cm['name']).value or '').strip()[:100] if 'name' in cm else '',
            summary=summ[:300], debit=debit, credit=credit,
            side='ap' if code.split('.')[0].startswith('2') else 'ar',
        ))
    for raw, n in unknown_books.items():
        unmatched[f'账簿未识别：{raw}'] = n
    return entries, unmatched, self_ref, skipped, errors


# ── 核算维度余额表解析 ─────────────────────────────────────────────────────────

def _detect_balance_sheet(ws):
    """识别金蝶「核算维度余额表」：主行含 组织机构名称/科目编码/账簿名称 与
    期初余额/本期发生额/期末余额 组头，次行为各组的 借方金额/贷方金额。
    返回 (data_start, cm) 或 (None, {})。cm: org/code/name/book +
    (open_d, open_c, cur_d, cur_c, close_d, close_c)。"""
    for ri in range(1, min(12, ws.max_row)):
        head = {str(ws.cell(row=ri, column=ci).value or '').strip(): ci
                for ci in range(1, min(ws.max_column + 1, 40))}
        if '组织机构名称' not in head or '账簿名称' not in head:
            continue
        cm = {'org': head['组织机构名称'], 'book': head['账簿名称']}
        if '科目编码' in head:
            cm['code'] = head['科目编码']
        if '科目名称' in head:
            cm['name'] = head['科目名称']
        if '币种' in head:
            cm['ccy'] = head['币种']
        # 组头（合并单元格只在起始列有值）→ 借/贷子列 = 组起始列 / +1
        groups = {}
        for ci in range(1, min(ws.max_column + 1, 40)):
            v = str(ws.cell(row=ri, column=ci).value or '').strip()
            if v in ('期初余额', '本期发生额', '期末余额'):
                sub1 = str(ws.cell(row=ri + 1, column=ci).value or '').strip()
                sub2 = str(ws.cell(row=ri + 1, column=ci + 1).value or '').strip()
                if '借' in sub1 and '贷' in sub2:
                    groups[v] = (ci, ci + 1)
        if '期末余额' not in groups:
            continue
        cm['close_d'], cm['close_c'] = groups['期末余额']
        if '期初余额' in groups:
            cm['open_d'], cm['open_c'] = groups['期初余额']
        if '本期发生额' in groups:
            cm['cur_d'], cm['cur_c'] = groups['本期发生额']
        return ri + 2, cm
    return None, {}


def _parse_balance(ws, data_start, cm, year, month):
    """→ (balances[未绑 batch], unmatched, skipped)。
    父子科目去重：同 (账簿, 组织) 组内若存在更细的子科目行（code 前缀+.），丢弃父行。"""
    raw_rows = []
    unmatched, skipped = {}, 0
    for ri in range(data_start, ws.max_row + 1):
        org_raw = str(ws.cell(row=ri, column=cm['org']).value or '').strip()
        book_raw = str(ws.cell(row=ri, column=cm['book']).value or '').strip()
        if not org_raw and not book_raw:
            skipped += 1
            continue
        if org_raw in _SKIP_SUMMARIES or book_raw in _SKIP_SUMMARIES:
            skipped += 1
            continue
        bu = _map_entity(book_raw)
        if not bu:
            unmatched[f'账簿未识别：{book_raw or "（空）"}'] = unmatched.get(f'账簿未识别：{book_raw or "（空）"}', 0) + 1
            skipped += 1
            continue
        cp = _map_entity(org_raw)
        if cp == bu:
            skipped += 1
            continue
        if not cp:
            unmatched[org_raw or '（空）'] = unmatched.get(org_raw or '（空）', 0) + 1
        code = str(ws.cell(row=ri, column=cm['code']).value or '').strip() if 'code' in cm else ''
        def g(key_d, key_c):
            if key_d not in cm:
                return Decimal('0'), Decimal('0')
            return (_cell_dec(ws.cell(row=ri, column=cm[key_d]).value),
                    _cell_dec(ws.cell(row=ri, column=cm[key_c]).value))
        od, oc = g('open_d', 'open_c')
        cd, cc = g('cur_d', 'cur_c')
        zd, zc = g('close_d', 'close_c')
        raw_rows.append({
            'bu': bu, 'cp': cp, 'cp_raw': org_raw, 'code': code,
            'ccy': str(ws.cell(row=ri, column=cm['ccy']).value or '').strip() if 'ccy' in cm else '',
            'name': str(ws.cell(row=ri, column=cm['name']).value or '').strip() if 'name' in cm else '',
            'opening': od - oc, 'debit': cd, 'credit': cc, 'closing': zd - zc,
        })
    # 多币种防双计：金蝶启用外币核算时同一余额会输出「人民币」与「综合本位币」两行，
    # 直接加总会翻倍——有人民币行时丢弃对应的综合本位币行；纯外币行不参与镜像核对。
    has_rmb = {(r['bu'], r['cp_raw'], r['code']) for r in raw_rows if r['ccy'] == '人民币'}
    kept = []
    for r in raw_rows:
        if r['ccy'] not in ('', '人民币', '综合本位币'):
            skipped += 1
            continue
        if r['ccy'] == '综合本位币' and (r['bu'], r['cp_raw'], r['code']) in has_rmb:
            skipped += 1
            continue
        kept.append(r)
    raw_rows = kept
    # 父子科目去重（2241 与 2241.04 同现时仅保留子科目）
    out = []
    for r in raw_rows:
        is_parent = any(o is not r and o['bu'] == r['bu'] and o['cp_raw'] == r['cp_raw']
                        and r['code'] and o['code'].startswith(r['code'] + '.')
                        for o in raw_rows)
        if is_parent:
            skipped += 1
            continue
        out.append(InternalBalance(
            business_unit=r['bu'], counterparty=r['cp'], counterparty_raw=r['cp_raw'][:200],
            year=year, month=month, subject_code=r['code'][:32], subject_name=r['name'][:100],
            opening=r['opening'], debit=r['debit'], credit=r['credit'], closing=r['closing'],
        ))
    return out, unmatched, skipped


# ── 端点 ─────────────────────────────────────────────────────────────────────

@csrf_exempt
@cw_required()
def internal_upload(request):
    """POST multipart：file (+可选 bu；year/month 作为余额表期间或明细兜底期间)。
    文件类型自动识别；明细账按（主体×期间）自动拆批；同键批次整体替换。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    if not (request.pk_role == 'super_admin' or _can_upload(request)):
        return err('无上传权限', 403)
    bu_param = (request.POST.get('bu') or '').strip()
    if bu_param and bu_param not in VALID_BUSINESS_UNITS:
        return err('记账主体无效')
    form_period = None
    try:
        y = int(request.POST.get('year', ''))
        m = int(request.POST.get('month', ''))
        if 2000 <= y <= 2100 and 1 <= m <= 12:
            form_period = (y, m)
    except Exception:
        pass
    f = request.FILES.get('file')
    if not f:
        return err('请上传文件')
    if f.size > IMPORT_SIZE_LIMIT:
        return err('文件过大（上限5MB）')
    ws, hint = _load_ws_any(f)   # .xlsx / 网页HTML / Excel2003 XML 皆可；老版 .xls 明确提示
    if ws is None:
        return err(hint)

    uploader = getattr(getattr(request, 'pk_user', None), 'name', '') or ''
    fname = (f.name or '')[:200]

    # 先试余额表，再试明细账
    bstart, bcm = _detect_balance_sheet(ws)
    if bstart is not None:
        if not form_period:
            return err('余额表不含期间信息，请在页面选择好年月后再上传')
        balances, unmatched, skipped = _parse_balance(ws, bstart, bcm, *form_period)
        if not balances:
            return err('未解析到任何余额行')
        combos = sorted({b.business_unit for b in balances})
        for bu in combos:
            if not _can_access_bu(request, bu):
                return err(f'您无权上传「{bu}」的数据（文件含该主体账簿）', 403)
        with transaction.atomic():
            InternalBatch.objects.filter(kind='balance', year=form_period[0],
                                         month=form_period[1],
                                         business_unit__in=combos).delete()
            batch_by_bu = {}
            for bu in combos:
                rows = [b for b in balances if b.business_unit == bu]
                batch = InternalBatch.objects.create(
                    business_unit=bu, year=form_period[0], month=form_period[1],
                    kind='balance', filename=fname, row_count=len(rows),
                    uploaded_by=uploader)
                for b in rows:
                    b.batch = batch
                batch_by_bu[bu] = batch
            InternalBalance.objects.bulk_create(balances, batch_size=500)
        return ok({
            'kind': 'balance', 'rows': len(balances), 'skipped': skipped,
            'batches': [batch_by_bu[bu].to_dict() for bu in combos],
            'unmatched': [{'raw': k, 'count': v} for k, v in
                          sorted(unmatched.items(), key=lambda kv: -kv[1])[:50]],
        })

    dstart, dcm = _detect_detail_ledger(ws)
    if dstart is None:
        return err('无法识别文件：请上传金蝶「明细分类账」（核算维度=组织机构）或'
                   '「核算维度余额表」导出的 xlsx')
    entries, unmatched, self_ref, skipped, errors = _parse_detail(ws, dstart, dcm, bu_param, form_period)
    if errors:
        return err('；'.join(errors))
    if not entries:
        return err('未解析到任何内部往来明细行（有效行需有借方或贷方金额）')
    if len(entries) > 100000:
        return err('明细超过10万行，请拆分导出后上传')
    combos = sorted({(e.business_unit, e.year, e.month) for e in entries})
    for bu in sorted({c[0] for c in combos}):
        if not _can_access_bu(request, bu):
            return err(f'您无权上传「{bu}」的数据（文件含该主体账簿）', 403)
    with transaction.atomic():
        batch_by_key = {}
        for bu, y, m in combos:
            InternalBatch.objects.filter(kind='detail', business_unit=bu,
                                         year=y, month=m).delete()
            rows_n = sum(1 for e in entries if (e.business_unit, e.year, e.month) == (bu, y, m))
            batch_by_key[(bu, y, m)] = InternalBatch.objects.create(
                business_unit=bu, year=y, month=m, kind='detail',
                filename=fname, row_count=rows_n, uploaded_by=uploader)
        for e in entries:
            e.batch = batch_by_key[(e.business_unit, e.year, e.month)]
        InternalEntry.objects.bulk_create(entries, batch_size=500)
    return ok({
        'kind': 'detail', 'rows': len(entries), 'skipped': skipped,
        'batches': [b.to_dict() for b in batch_by_key.values()],
        'unmatched': [{'raw': k, 'count': v} for k, v in
                      sorted(unmatched.items(), key=lambda kv: -kv[1])[:50]],
        'self_ref': [{'raw': k, 'count': v} for k, v in
                     sorted(self_ref.items(), key=lambda kv: -kv[1])[:50]],
    })


@csrf_exempt
@cw_required()
def internal_batches(request):
    """GET ?year=&month= → 各主体明细/余额上传覆盖情况。"""
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', ''))
        month = int(request.GET.get('month', ''))
    except Exception:
        return err('年份或月份无效')
    by_bu = {}
    for b in InternalBatch.objects.filter(year=year, month=month):
        by_bu.setdefault(b.business_unit, {})[b.kind] = b.to_dict()
    return ok({'units': BUSINESS_UNITS,
               'batches': [by_bu.get(bu) or None for bu in BUSINESS_UNITS]})


@csrf_exempt
@cw_required()
def internal_batch_detail(request, bid):
    if request.method != 'DELETE':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    if not (request.pk_role == 'super_admin' or _can_delete(request)):
        return err('无删除权限', 403)
    try:
        batch = InternalBatch.objects.get(id=bid)
    except InternalBatch.DoesNotExist:
        return err('批次不存在', 404)
    if not _can_access_bu(request, batch.business_unit):
        return err('无权操作该主体数据', 403)
    batch.delete()
    return ok({'deleted': bid})


@csrf_exempt
@cw_required()
def internal_clear(request):
    """超管一键清除内部往来数据。body: {scope, year?, month?, bu?}
    scope=month → 该年月全部主体；bu → 该主体全部期间；all → 全部。
    删除 InternalBatch（级联 entries + balances）。仅超级管理员可用（破坏性批量操作）。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    if request.pk_role != 'super_admin':
        return err('仅超级管理员可一键清除', 403, 403)
    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except (ValueError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict) or not data:
        data = request.POST
    scope = (data.get('scope') or '').strip()

    qs = InternalBatch.objects.all()
    if scope == 'month':
        try:
            y = int(data.get('year')); m = int(data.get('month'))
            assert 2000 <= y <= 2100 and 1 <= m <= 12
        except (TypeError, ValueError, AssertionError):
            return err('年月无效')
        qs = qs.filter(year=y, month=m)
        label = f'{y}年{m}月'
    elif scope == 'bu':
        bu = (data.get('bu') or '').strip()
        if bu not in VALID_BUSINESS_UNITS:
            return err('记账主体无效')
        qs = qs.filter(business_unit=bu)
        label = bu
    elif scope == 'all':
        label = '全部'
    else:
        return err('清除范围无效（month / bu / all）')

    n_batch = qs.count()
    n_entry = InternalEntry.objects.filter(batch__in=qs).count()
    n_bal = InternalBalance.objects.filter(batch__in=qs).count()
    qs.delete()   # 级联删除 entries + balances
    logger.warning('internal-clear uid=%s scope=%s label=%s batches=%s entries=%s balances=%s',
                   request.pk_uid, scope, label, n_batch, n_entry, n_bal)
    return ok({'scope': scope, 'label': label,
               'batches': n_batch, 'entries': n_entry, 'balances': n_bal})


def _positions(year, month):
    """→ (positions{(bu,cp): Decimal}, mode)。余额批次存在→期末余额口径；否则本期发生。"""
    bal = (InternalBalance.objects.filter(year=year, month=month)
           .exclude(counterparty='')
           .values('business_unit', 'counterparty')
           .annotate(net=Sum('closing')))
    if bal:
        return {(r['business_unit'], r['counterparty']): (r['net'] or Decimal('0'))
                for r in bal}, 'balance'
    det = (InternalEntry.objects.filter(year=year, month=month)
           .exclude(counterparty='')
           .values('business_unit', 'counterparty')
           .annotate(net=Sum(F('debit') - F('credit'))))
    return {(r['business_unit'], r['counterparty']): (r['net'] or Decimal('0'))
            for r in det}, 'detail'


@csrf_exempt
@cw_required()
def internal_matrix(request):
    """GET ?year=&month= → 全集团差异矩阵 + KPI + 差异对排行。
    余额数据存在时按期末余额口径（含期初遗留差异），否则按本期发生净额。"""
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', ''))
        month = int(request.GET.get('month', ''))
    except Exception:
        return err('年份或月份无效')
    pos, mode = _positions(year, month)
    kind = 'balance' if mode == 'balance' else 'detail'
    uploaded = set(InternalBatch.objects.filter(year=year, month=month, kind=kind)
                   .values_list('business_unit', flat=True))
    units = BUSINESS_UNITS
    cells = [[(float(pos.get((a, b), 0)) if a != b else None) for b in units] for a in units]
    pair_diffs, seen = [], set()
    for a in units:
        for b in units:
            if a == b or (b, a) in seen:
                continue
            seen.add((a, b))
            pa, pb = pos.get((a, b), Decimal('0')), pos.get((b, a), Decimal('0'))
            if not pa and not pb:
                continue
            pair_diffs.append({
                'a': a, 'b': b, 'a_net': float(pa), 'b_net': float(pb),
                'diff': float(pa + pb),
                'both_uploaded': a in uploaded and b in uploaded,
            })
    pair_diffs.sort(key=lambda p: -abs(p['diff']))
    total_ar = sum(float(v) for v in pos.values() if v > 0)
    total_ap = -sum(float(v) for v in pos.values() if v < 0)
    total_diff = sum(abs(p['diff']) for p in pair_diffs if p['both_uploaded'])
    unmatched_cnt = (
        InternalBalance.objects.filter(year=year, month=month, counterparty='').count()
        if mode == 'balance'
        else InternalEntry.objects.filter(year=year, month=month, counterparty='').count())
    return ok({
        'units': units, 'uploaded': sorted(uploaded), 'cells': cells,
        'pairs': pair_diffs, 'mode': mode,
        'kpi': {
            'total_ar': total_ar, 'total_ap': total_ap, 'total_diff': total_diff,
            'pairs_total': sum(1 for p in pair_diffs if p['both_uploaded']),
            'pairs_ok': sum(1 for p in pair_diffs
                            if p['both_uploaded'] and abs(p['diff']) < 0.005),
            'unmatched_rows': unmatched_cnt,
        },
    })


def _auto_match(a_rows, b_rows):
    """镜像自动配对：|signed| 相等且方向相反的行 1:1 贪心配对（同额按日期先后）。"""
    a_out = [r.to_dict() for r in a_rows]
    b_out = [r.to_dict() for r in b_rows]
    from collections import defaultdict
    pool = defaultdict(list)
    for i, r in enumerate(b_out):
        amt = abs(r['signed'])
        if amt:
            pool[f'{amt:.2f}'].append(i)
    gid = 0
    matched_amount = 0.0
    for r in a_out:
        r['match'] = None
    for r in b_out:
        r['match'] = None
    for ra in a_out:
        amt = abs(ra['signed'])
        if not amt:
            continue
        cand = pool.get(f'{amt:.2f}') or []
        # 镜像要求 signed 反号；同号候选保留给后续反号行
        for k, j in enumerate(cand):
            if b_out[j]['signed'] * ra['signed'] < 0:
                cand.pop(k)
                gid += 1
                ra['match'] = gid
                b_out[j]['match'] = gid
                matched_amount += amt
                break
    return a_out, b_out, matched_amount


def _pair_balance(year, month, a, b):
    """两主体的余额镜像摘要（期初/本期/期末，双侧）；无余额数据返回 None。"""
    def side(bu, cp):
        agg = (InternalBalance.objects
               .filter(year=year, month=month, business_unit=bu, counterparty=cp)
               .aggregate(o=Sum('opening'), d=Sum('debit'), c=Sum('credit'), z=Sum('closing')))
        if agg['z'] is None and agg['o'] is None and agg['d'] is None:
            return None
        return {'opening': float(agg['o'] or 0), 'debit': float(agg['d'] or 0),
                'credit': float(agg['c'] or 0), 'closing': float(agg['z'] or 0)}
    sa, sb = side(a, b), side(b, a)
    if sa is None and sb is None:
        return None
    sa = sa or {'opening': 0, 'debit': 0, 'credit': 0, 'closing': 0}
    sb = sb or {'opening': 0, 'debit': 0, 'credit': 0, 'closing': 0}
    return {'a': sa, 'b': sb,
            'opening_diff': sa['opening'] + sb['opening'],
            'closing_diff': sa['closing'] + sb['closing']}


@csrf_exempt
@cw_required()
def internal_pair(request):
    """GET ?year=&month=&a=&b= → 双侧明细自动配对 + 余额镜像摘要（如已传余额表）。"""
    denied = _page_denied(request, 'internal')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', ''))
        month = int(request.GET.get('month', ''))
    except Exception:
        return err('年份或月份无效')
    a = (request.GET.get('a') or '').strip()
    b = (request.GET.get('b') or '').strip()
    if a not in VALID_BUSINESS_UNITS or b not in VALID_BUSINESS_UNITS or a == b:
        return err('请选择两个不同的主体')
    a_rows = list(InternalEntry.objects
                  .filter(year=year, month=month, business_unit=a, counterparty=b)
                  .order_by('biz_date', 'id'))
    b_rows = list(InternalEntry.objects
                  .filter(year=year, month=month, business_unit=b, counterparty=a)
                  .order_by('biz_date', 'id'))
    a_out, b_out, matched_amount = _auto_match(a_rows, b_rows)
    a_net = sum(r['signed'] for r in a_out)
    b_net = sum(r['signed'] for r in b_out)
    uploaded = set(InternalBatch.objects
                   .filter(year=year, month=month, kind='detail', business_unit__in=[a, b])
                   .values_list('business_unit', flat=True))
    return ok({
        'a': a, 'b': b,
        'a_rows': a_out, 'b_rows': b_out,
        'a_net': float(a_net), 'b_net': float(b_net),
        'diff': float(a_net + b_net),
        'matched_amount': matched_amount,
        'matched_pairs': sum(1 for r in a_out if r['match']),
        'a_uploaded': a in uploaded, 'b_uploaded': b in uploaded,
        'balance': _pair_balance(year, month, a, b),
    })

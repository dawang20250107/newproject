import logging
from decimal import Decimal
from django.http import JsonResponse
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce, TruncMonth
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, serializers

from wxcloudrun.models import Project, ReceivableData, PaymentRegistration

logger = logging.getLogger('wxcloudrun')


def to_f(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def ok(data):
    return JsonResponse({'code': 0, 'data': data})


def err(msg, code=-1):
    return JsonResponse({'code': code, 'error': msg}, status=400)


def ds(qs, field):
    return float(qs.aggregate(s=Coalesce(Sum(field, output_field=DecimalField()), Decimal('0')))['s'] or 0)


# ─── 主页 ─────────────────────────────────────────────────

def index(request):
    return JsonResponse({'code': 0, 'msg': 'KXT API Running', 'version': '2.0.0'})


# ─── DRF Serializers ──────────────────────────────────────

class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'project_name', 'project_code', 'customer_name', 'manager_name',
                  'contract_amount', 'business_model', 'department', 'sales_contact',
                  'shared_type', 'settlement_cycle', 'total_zhangqi', 'created_at']


class ReceivableDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceivableData
        fields = ['id', 'project_name', 'manager_name', 'month',
                  'receivable_amount', 'received_amount', 'unpaid_amount', 'status']


class PaymentRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRegistration
        fields = ['id', 'applicant_name', 'invoice_no', 'description', 'project_name',
                  'planned_date', 'apply_amount', 'paid_amount', 'pay_date',
                  'payment_manager', 'is_paid', 'has_invoice']


# ─── DRF ViewSets ─────────────────────────────────────────

class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def list(self, request):
        return projects_erp_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except Project.DoesNotExist:
            return err('项目不存在', code=404)
        return ok(self.get_serializer(obj).data)


class ReceivableDataViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = ReceivableData.objects.all()
    serializer_class = ReceivableDataSerializer

    def list(self, request):
        return receivables_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except ReceivableData.DoesNotExist:
            return err('记录不存在', code=404)
        return ok(self.get_serializer(obj).data)


class PaymentRegistrationViewSet(viewsets.ModelViewSet):
    permission_classes = []
    authentication_classes = []
    queryset = PaymentRegistration.objects.all()
    serializer_class = PaymentRegistrationSerializer

    def list(self, request):
        return payables_registrations_list(request)

    def retrieve(self, request, pk=None):
        try:
            obj = self.get_queryset().get(pk=pk)
        except PaymentRegistration.DoesNotExist:
            return err('记录不存在', code=404)
        return ok(self.get_serializer(obj).data)


# ─── 仪表板 API ───────────────────────────────────────────

def dashboard_kpi(request):
    """GET /api/dashboard/kpi"""
    try:
        all_rs = ReceivableData.objects.all()
        normal_rs = all_rs.filter(unpaid_amount=0)
        overdue_rs = all_rs.filter(status='abnormal')

        def calc(qs):
            total = ds(qs, 'receivable_amount')
            received = ds(qs, 'received_amount')
            unpaid = ds(qs, 'unpaid_amount')
            rate = round(received / total * 100, 2) if total > 0 else 0
            return {
                'receivable': round(total, 2),
                'receivable_display': f'{round(total / 10000, 2)}',
                'received': round(received, 2),
                'received_display': f'{round(received / 10000, 2)}',
                'unpaid': round(unpaid, 2),
                'unpaid_display': f'{round(unpaid / 10000, 2)}',
                'completion_rate': rate,
            }

        overdue_projects = all_rs.filter(status='abnormal').values('project_name').distinct().count()
        latest = all_rs.exclude(month='').order_by('-month').first()
        return ok({
            'row1': calc(all_rs),
            'row2': calc(normal_rs),
            'row3': calc(overdue_rs),
            'total_projects': Project.objects.count(),
            'overdue_projects': overdue_projects,
            'update_time': latest.month if latest else '',
        })
    except Exception as e:
        logger.error(f'[KPI] {e}')
        return err(str(e))


def dashboard_abnormal_ranking(request):
    """GET /api/dashboard/abnormal-ranking"""
    try:
        managers = {}
        for r in ReceivableData.objects.filter(status='abnormal'):
            key = r.manager_name or '未知'
            if key not in managers:
                managers[key] = {'count': 0, 'unpaid': 0.0}
            managers[key]['count'] += 1
            managers[key]['unpaid'] += to_f(r.unpaid_amount)

        data = sorted([
            {'manager_name': k, 'alert_count': v['count'], 'total_abnormal': round(v['unpaid'], 2)}
            for k, v in managers.items()
        ], key=lambda x: -x['total_abnormal'])[:20]
        return ok(data)
    except Exception as e:
        logger.error(f'[AbnormalRanking] {e}')
        return err(str(e))


def dashboard_unpaid_distribution(request):
    """GET /api/dashboard/unpaid-distribution"""
    try:
        proj_unpaid = {}
        for r in ReceivableData.objects.filter(unpaid_amount__gt=0):
            key = r.project_name or '未知项目'
            proj_unpaid[key] = proj_unpaid.get(key, 0) + to_f(r.unpaid_amount)

        data = sorted([
            {'name': k, 'value': round(v, 2)} for k, v in proj_unpaid.items()
        ], key=lambda x: -x['value'])[:20]
        return ok(data)
    except Exception as e:
        logger.error(f'[UnpaidDist] {e}')
        return err(str(e))


def dashboard_manager_comparison(request):
    """GET /api/dashboard/manager-comparison"""
    try:
        managers = {}
        for r in ReceivableData.objects.all():
            key = r.manager_name or '未知'
            if key not in managers:
                managers[key] = {'receivable': 0.0, 'received': 0.0, 'unpaid': 0.0, 'projects': set()}
            managers[key]['receivable'] += to_f(r.receivable_amount)
            managers[key]['received'] += to_f(r.received_amount)
            managers[key]['unpaid'] += to_f(r.unpaid_amount)
            managers[key]['projects'].add(r.project_name)

        data = sorted([
            {
                'manager_name': k,
                'receivable': round(v['receivable'], 2),
                'received': round(v['received'], 2),
                'unpaid': round(v['unpaid'], 2),
                'project_count': len(v['projects']),
                'completion_rate': round(v['received'] / v['receivable'] * 100, 2) if v['receivable'] > 0 else 0,
            }
            for k, v in managers.items()
        ], key=lambda x: -x['receivable'])
        return ok(data)
    except Exception as e:
        logger.error(f'[ManagerComparison] {e}')
        return err(str(e))


def dashboard_manager_detail(request):
    """GET /api/dashboard/manager/detail?manager=<name>"""
    try:
        import urllib.parse
        manager = urllib.parse.unquote(request.GET.get('manager', ''))
        if not manager:
            return err('缺少 manager 参数')

        records = ReceivableData.objects.filter(manager_name=manager)
        items = []
        seen = set()
        for r in records.order_by('project_name', '-month'):
            pname = r.project_name or ''
            if pname in seen:
                continue
            seen.add(pname)
            proj_recs = list(records.filter(project_name=pname).order_by('-month'))
            items.append({
                'project_name': pname,
                'abnormal_amount': round(sum(to_f(rr.receivable_amount) for rr in proj_recs), 2),
                'received_amount': round(sum(to_f(rr.received_amount) for rr in proj_recs), 2),
                'unpaid_amount': round(sum(to_f(rr.unpaid_amount) for rr in proj_recs), 2),
                'days_overdue': 0,
                'status': proj_recs[0].status or 'normal',
                'record_date': proj_recs[0].month or '',
                'sub_records': [
                    {
                        'month': rr.month or '',
                        'abnormal_amount': to_f(rr.receivable_amount),
                        'received_amount': to_f(rr.received_amount),
                        'unpaid_amount': to_f(rr.unpaid_amount),
                        'status': rr.status or 'normal',
                    }
                    for rr in proj_recs
                ],
            })
        return ok({'items': items})
    except Exception as e:
        logger.error(f'[ManagerDetail] {e}')
        return err(str(e))


def dashboard_projects_monthly(request):
    """GET /api/dashboard/projects-monthly — 月度已收 vs 已付"""
    try:
        target_month = request.GET.get('month', '').strip()
        monthly = {}
        for r in ReceivableData.objects.exclude(month=''):
            m = r.month
            if m not in monthly:
                monthly[m] = {'received': 0.0, 'paid': 0.0}
            monthly[m]['received'] += to_f(r.received_amount)

        paid_qs = (
            PaymentRegistration.objects
            .filter(planned_date__isnull=False, paid_amount__gt=0)
            .annotate(pay_month=TruncMonth('planned_date'))
            .values('pay_month')
            .annotate(paid=Sum('paid_amount', output_field=DecimalField()))
            .order_by('pay_month')
        )
        for row in paid_qs:
            m = str(row['pay_month'])[:7]
            if m not in monthly:
                monthly[m] = {'received': 0.0, 'paid': 0.0}
            monthly[m]['paid'] = float(row['paid'])

        months = sorted(monthly.keys())
        if target_month:
            months = [m for m in months if m == target_month]

        result = [
            {'month': m, 'received': round(monthly[m]['received'], 2), 'paid': round(monthly[m]['paid'], 2)}
            for m in months
        ]
        return ok({
            'monthly_received': round(sum(r['received'] for r in result), 2),
            'monthly_paid': round(sum(r['paid'] for r in result), 2),
            'months': result,
        })
    except Exception as e:
        logger.error(f'[ProjectsMonthly] {e}')
        return err(str(e))


def dashboard_monthly_abnormal(request):
    """GET /api/dashboard/monthly-abnormal — 月度逾期统计"""
    try:
        monthly = {}
        for r in ReceivableData.objects.filter(status='abnormal').exclude(month=''):
            m = r.month
            if m not in monthly:
                monthly[m] = {'count': 0, 'unpaid': 0.0}
            monthly[m]['count'] += 1
            monthly[m]['unpaid'] += to_f(r.unpaid_amount)

        result = [
            {'month': m, 'count': monthly[m]['count'], 'unpaid': round(monthly[m]['unpaid'], 2)}
            for m in sorted(monthly.keys())
        ]
        return ok(result)
    except Exception as e:
        logger.error(f'[MonthlyAbnormal] {e}')
        return err(str(e))


# ─── 项目 API ─────────────────────────────────────────────

def project_list(request):
    """GET /api/projects — 按项目名聚合 ReceivableData"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()

        qs = ReceivableData.objects.all()
        if keyword:
            qs = qs.filter(Q(project_name__icontains=keyword) | Q(manager_name__icontains=keyword))

        seen = {}
        for r in qs.order_by('project_name', '-month'):
            pname = r.project_name or ''
            if pname not in seen:
                seen[pname] = {
                    'manager': r.manager_name or '',
                    'status': r.status or 'normal',
                    'record_date': r.month,
                    'total_estimated': 0.0,
                    'total_received': 0.0,
                    'total_unpaid': 0.0,
                    'all_recs': [],
                }
            seen[pname]['total_estimated'] += to_f(r.receivable_amount)
            seen[pname]['total_received'] += to_f(r.received_amount)
            seen[pname]['total_unpaid'] += to_f(r.unpaid_amount)
            seen[pname]['all_recs'].append(r)

        items_data = sorted(seen.items(), key=lambda x: -x[1]['total_unpaid'])
        total = len(items_data)
        offset = (page - 1) * page_size
        items = []
        for pname, info in items_data[offset:offset + page_size]:
            sub_items = [
                {
                    'id': r.id,
                    'record_date': r.month or '',
                    'manager_name': r.manager_name or '',
                    'abnormal_amount': to_f(r.receivable_amount),
                    'received_amount': to_f(r.received_amount),
                    'unpaid_amount': to_f(r.unpaid_amount),
                    'days_overdue': 0,
                    'status': r.status or 'normal',
                }
                for r in info['all_recs']
            ]
            items.append({
                'project_name': pname,
                'manager_name': info['manager'],
                'status': info['status'],
                'record_date': info['record_date'] or '',
                'abnormal_amount': round(info['total_estimated'], 2),
                'received_amount': round(info['total_received'], 2),
                'unpaid_amount': round(info['total_unpaid'], 2),
                'days_overdue': 0,
                'has_detail': len(sub_items) > 1,
                'sub_items': sub_items,
            })
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[ProjectList] {e}')
        return err(str(e))


def project_detail(request, project_id):
    """GET /api/projects/<id>"""
    try:
        try:
            record = ReceivableData.objects.get(id=project_id)
        except ReceivableData.DoesNotExist:
            return err('项目不存在', code=404)

        proj_recs = list(ReceivableData.objects.filter(project_name=record.project_name).order_by('-month'))
        return ok({
            'id': record.id,
            'project_name': record.project_name or '',
            'manager_name': record.manager_name or '',
            'abnormal_amount': to_f(record.receivable_amount),
            'received_amount': to_f(record.received_amount),
            'unpaid_amount': to_f(record.unpaid_amount),
            'days_overdue': 0,
            'status': record.status or 'normal',
            'record_date': record.month or '',
            'receivable_history': [
                {
                    'month': r.month or '',
                    'receivable_amount': to_f(r.receivable_amount),
                    'received_amount': to_f(r.received_amount),
                    'status': r.status or 'normal',
                }
                for r in proj_recs
            ],
        })
    except Exception as e:
        logger.error(f'[ProjectDetail] {e}')
        return err(str(e))


# ─── ERP 项目 API ──────────────────────────────────────────

def projects_erp_list(request):
    """GET /api/projects-erp"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = Project.objects.all()
        if keyword:
            qs = qs.filter(
                Q(project_name__icontains=keyword) |
                Q(project_code__icontains=keyword) |
                Q(manager_name__icontains=keyword)
            )
        total = qs.count()
        items = [
            {
                'id': r.id,
                'project_name': r.project_name or '',
                'project_alias': r.project_code or '',
                'business_mode': r.business_model or '',
                'department': r.department or '',
                'manager_name': r.manager_name or '',
                'sales_contact': r.sales_contact or '',
                'share_type': r.shared_type or '',
                'settlement_cycle': r.settlement_cycle or '',
                'reconciliation_period': '',
                'invoice_wait_period': '',
                'payment_period': '',
                'total_period': r.total_zhangqi or '',
                'invoice_mode': '',
                'created_at': str(r.created_at)[:10] if r.created_at else '',
            }
            for r in qs[(page-1)*page_size: page*page_size]
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[ProjectsERPList] {e}')
        return err(str(e))


def project_erp_detail(request, project_id):
    """GET /api/projects-erp/<id>"""
    try:
        try:
            p = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return err('项目不存在', code=404)
        return ok({
            'id': p.id,
            'project_name': p.project_name or '',
            'project_alias': p.project_code or '',
            'business_mode': p.business_model or '',
            'department': p.department or '',
            'manager_name': p.manager_name or '',
            'sales_contact': p.sales_contact or '',
            'share_type': p.shared_type or '',
            'settlement_cycle': p.settlement_cycle or '',
            'reconciliation_period': '',
            'invoice_wait_period': '',
            'payment_period': '',
            'total_period': p.total_zhangqi or '',
            'invoice_mode': '',
            'created_at': str(p.created_at)[:10] if p.created_at else '',
        })
    except Exception as e:
        logger.error(f'[ProjectERPDetail] {e}')
        return err(str(e))


def project_erp_summary(request):
    """GET /api/projects-erp/summary"""
    try:
        total = Project.objects.count()
        managers = Project.objects.values('manager_name').distinct().count()
        return ok({'total_projects': total, 'total_managers': managers, 'new_this_month': 0})
    except Exception as e:
        logger.error(f'[ProjectERPSummary] {e}')
        return err(str(e))


# ─── 应收账款 API ──────────────────────────────────────────

def receivables_list(request):
    """GET /api/receivables"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = ReceivableData.objects.all()
        if keyword:
            qs = qs.filter(Q(project_name__icontains=keyword) | Q(manager_name__icontains=keyword))
        total = qs.count()
        items = [
            {
                'id': r.id,
                'project_name': r.project_name or '',
                'contract_name': r.project_name or '',
                'manager_name': r.manager_name or '',
                'month': r.month or '',
                'receivable_amount': to_f(r.receivable_amount),
                'received_amount': to_f(r.received_amount),
                'unpaid_amount': to_f(r.unpaid_amount),
                'status': r.status or 'normal',
            }
            for r in qs[(page-1)*page_size: page*page_size]
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[ReceivablesList] {e}')
        return err(str(e))


# ─── 应付管理 API ──────────────────────────────────────────

def payables_registrations_list(request):
    """GET /api/payables/registrations"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        keyword = request.GET.get('keyword', '').strip()
        qs = PaymentRegistration.objects.all()
        if keyword:
            qs = qs.filter(
                Q(applicant_name__icontains=keyword) |
                Q(project_name__icontains=keyword) |
                Q(description__icontains=keyword)
            )
        total = qs.count()
        items = [
            {
                'id': r.id,
                'applicant': r.applicant_name or '',
                'dingtalk_id': r.invoice_no or '',
                'summary': r.description or '',
                'project': r.project_name or '',
                'planned_date': str(r.planned_date)[:10] if r.planned_date else '',
                'apply_amount': to_f(r.apply_amount),
                'paid_amount': to_f(r.paid_amount),
                'pay_date': str(r.pay_date)[:10] if r.pay_date else '',
                'payment_entity': r.payment_manager or '',
                'is_planned': bool(r.is_paid),
                'has_invoice': bool(r.has_invoice),
            }
            for r in qs[(page-1)*page_size: page*page_size]
        ]
        return ok({'total': total, 'page': page, 'page_size': page_size, 'items': items})
    except Exception as e:
        logger.error(f'[PayablesList] {e}')
        return err(str(e))


def payables_registrations_summary(request):
    """GET /api/payables/registrations/summary"""
    try:
        all_exp = list(PaymentRegistration.objects.all())
        total_apply = sum(to_f(r.apply_amount) for r in all_exp)
        total_paid = sum(to_f(r.paid_amount) for r in all_exp)
        return ok({
            'total_apply': round(total_apply, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_apply - total_paid, 2),
            'total_count': len(all_exp),
            'paid_count': sum(1 for r in all_exp if r.is_paid),
        })
    except Exception as e:
        logger.error(f'[PayablesSummary] {e}')
        return err(str(e))


# ─── 同步 API ─────────────────────────────────────────────

@csrf_exempt
def sync_from_docs(request):
    """POST /api/sync/from-docs"""
    if request.method != 'POST':
        return err('仅支持 POST 请求', code=405)
    try:
        from io import StringIO
        from django.core.management import call_command
        buf = StringIO()
        call_command('sync_from_docs', stdout=buf)
        output = buf.getvalue()
        logger.info(f'[SyncFromDocs] 同步完成: {output[:200]}')
        return ok({'message': '同步完成', 'output': output})
    except Exception as e:
        logger.error(f'[SyncFromDocs] {e}')
        return err(f'同步失败: {e}')

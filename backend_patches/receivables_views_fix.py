from rest_framework import viewsets
from .models import Receivable
from .serializers import ReceivableSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Count


class ReceivableViewSet(viewsets.ModelViewSet):
    """应收账款"""
    queryset = Receivable.objects.select_related('project').all()
    serializer_class = ReceivableSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        month = self.request.query_params.get('month', '')
        keyword = self.request.query_params.get('search', '')
        s = self.request.query_params.get('status', '')
        ordering = self.request.query_params.get('ordering', '').strip()
        manager_name = self.request.query_params.get('manager_name', '')

        if project_id:
            qs = qs.filter(project_id=project_id)
        if month:
            qs = qs.filter(month=month)
        if keyword:
            qs = qs.filter(
                project__project_name__icontains=keyword
            ) | qs.filter(
                project__project_code__icontains=keyword
            )
        if s:
            qs = qs.filter(status=s)
        if manager_name:
            qs = qs.filter(project__manager_name=manager_name)

        # 排序 - 默认按月份升序（最旧的在前）
        if ordering:
            field_map = {
                'month': 'month', '-month': '-month',
                'receivable_amount': 'receivable_amount', '-receivable_amount': '-receivable_amount',
                'received_amount': 'received_amount', '-received_amount': '-received_amount',
                'project_name': 'project__project_name', '-project_name': '-project__project_name',
                'created_at': 'created_at', '-created_at': '-created_at',
                'id': 'id', '-id': '-id',
            }
            order_field = field_map.get(ordering, 'month')
            qs = qs.order_by(order_field)
        else:
            qs = qs.order_by('month')  # 默认升序

        return qs


class ReceivableMonthlyView(APIView):
    """应收账款月度汇总"""

    def get(self, request):
        month = request.query_params.get('month', '')
        # 按月汇总，不显示当月（只看3月及以前的数据）
        qs = Receivable.objects.select_related('project').all()

        rows = qs.values('month').annotate(
            total_receivable=Sum('receivable_amount'),
            total_received=Sum('received_amount'),
            total_unpaid=Sum('receivable_amount') - Sum('received_amount'),
            count=Count('id'),
        ).order_by('month')

        # 逾期统计（status=abnormal）
        overdue_rows = qs.filter(status='abnormal').values('month').annotate(
            overdue_count=Count('id'),
            overdue_amount=Sum('receivable_amount'),
        )

        overdue_map = {r['month']: r for r in overdue_rows}

        results = []
        for r in rows:
            m = r['month']
            ov = overdue_map.get(m, {})
            results.append({
                'month': m,
                'total_receivable': float(r['total_receivable'] or 0),
                'total_received': float(r['total_received'] or 0),
                'total_unpaid': float(r['total_unpaid'] or 0),
                'record_count': r['count'],
                'overdue_count': ov.get('overdue_count', 0),
                'overdue_amount': float(ov.get('overdue_amount') or 0),
            })

        return Response({'monthly': results})

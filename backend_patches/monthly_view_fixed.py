from rest_framework.views import APIView
from rest_framework.response import Response
from projects.models import Project
from receivables.models import Receivable
from payables.models import Payable
from django.db.models import Sum, Count
from django.db import connection
from django.utils import timezone


class MonthlyReceivedPaidView(APIView):
    """
    月度已收 vs 已付对比
    """

    def get(self, request):
        target_month = request.query_params.get('month', '').strip()

        # 已收: 从 receivable_data
        recv_qs = Receivable.objects.values('month').annotate(
            received=Sum('received_amount')
        ).order_by('month')

        # 已付: 从 payment_registrations (paid_amount)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT CONCAT(YEAR(planned_date), '-', LPAD(MONTH(planned_date), 2, '0')) as pay_month,
                       SUM(paid_amount) as paid
                FROM payment_registrations
                WHERE planned_date IS NOT NULL AND paid_amount > 0
                GROUP BY pay_month
                ORDER BY pay_month
            """)
            paid_rows = {}
            for row in cur.fetchall():
                paid_rows[str(row[0])] = float(row[1])

        # Merge by month
        months_map = {}
        for r in recv_qs:
            m = str(r['month'])
            months_map.setdefault(m, {'month': m, 'received': 0.0, 'paid': 0.0})
            months_map[m]['received'] = float(r['received'] or 0)

        for m, p in paid_rows.items():
            months_map.setdefault(m, {'month': m, 'received': 0.0, 'paid': 0.0})
            months_map[m]['paid'] = p

        months = sorted(months_map.values(), key=lambda x: x['month'])

        if target_month:
            filtered = [m for m in months if m['month'] == target_month]
            months = filtered

        total_received = sum(m['received'] for m in months)
        total_paid = sum(m['paid'] for m in months)

        return Response({
            'monthly_received': round(total_received, 2),
            'monthly_paid': round(total_paid, 2),
            'months': months,
        })

from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Contract
from .serializers import ContractSerializer


class ContractViewSet(viewsets.ModelViewSet):
    """合同管理 CRUD"""
    queryset = Contract.objects.select_related('project').all()
    serializer_class = ContractSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '')
        project_id = self.request.query_params.get('project_id')
        s = self.request.query_params.get('status', '')
        period = self.request.query_params.get('period', '')
        if keyword:
            qs = qs.filter(contract_name__icontains=keyword) | qs.filter(contract_no__icontains=keyword) | qs.filter(party_a__icontains=keyword) | qs.filter(party_b__icontains=keyword)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if s:
            qs = qs.filter(status=s)
        # period: 短期(≤1年)=短期, >1年=长期
        if period == '短期':
            qs = qs.filter(expire_date__isnull=False)
        elif period == '长期':
            qs = qs.filter(expire_date__isnull=True)
        return qs

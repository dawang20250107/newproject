from rest_framework import serializers
from .models import Contract


class ContractSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.project_name', read_only=True)

    class Meta:
        model = Contract
        fields = ['id', 'project', 'project_name', 'contract_no', 'contract_name',
                  'party_a', 'party_b', 'amount', 'signing_date', 'expire_date',
                  'status', 'file_url', 'remarks', 'created_at', 'updated_at', 'period']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Add computed period field
        if instance.expire_date and instance.signing_date:
            from datetime import date
            delta = (instance.expire_date - instance.signing_date).days
            data['period'] = '长期' if delta > 365 else '短期'
        elif instance.expire_date:
            data['period'] = '长期'
        else:
            data['period'] = ''
        return data

from rest_framework import serializers
from .models import OrganizationNodeType, OrganizationNode, OrganizationAuditLog

class OrganizationNodeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationNodeType
        fields = '__all__'

class OrganizationNodeSerializer(serializers.ModelSerializer):
    node_type = OrganizationNodeTypeSerializer(read_only=True)
    node_type_id = serializers.PrimaryKeyRelatedField(
        queryset=OrganizationNodeType.objects.all(), source='node_type', write_only=True
    )
    
    # We will compute children dynamically for tree views, but we can include a read-only list of child IDs here if needed
    children = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationNode
        fields = '__all__'
        read_only_fields = ['path', 'depth']

    def get_children(self, obj):
        # Only return minimal info to avoid deep nesting issues if we aren't careful
        # A specific recursive endpoint will handle full tree delivery
        return obj.children.values('id', 'name', 'node_type__name')

class OrganizationAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationAuditLog
        fields = '__all__'

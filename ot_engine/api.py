from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import OTPolicy, OTThresholdConfig, OTRequest, CompOffBalance
from rest_framework import serializers

class OTPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = OTPolicy
        fields = '__all__'

class OTRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTRequest
        fields = '__all__'

class CompOffBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompOffBalance
        fields = '__all__'

class OTPolicyViewSet(viewsets.ModelViewSet):
    queryset = OTPolicy.objects.all()
    serializer_class = OTPolicySerializer
    permission_classes = [permissions.IsAuthenticated]

class OTRequestViewSet(viewsets.ModelViewSet):
    queryset = OTRequest.objects.all()
    serializer_class = OTRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        ot_req = self.get_object()
        # Single point API for approval (simplified for brevity)
        ot_req.status = 'Approved'
        ot_req.save()
        return Response({"status": "Approved"})

class CompOffViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CompOffBalance.objects.all()
    serializer_class = CompOffBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return self.queryset.filter(employee__user=self.request.user)

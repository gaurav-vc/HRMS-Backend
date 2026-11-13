# core/telemetry_urls.py
from django.urls import path
from core.telemetry_views import (
    TelemetryOverviewAPIView,
    TelemetrySyntheticRunAPIView,
    TelemetryResolveAnomalyAPIView,
    SimulateAnomalyAPIView,
    ProberToggleAPIView,
    EndpointsCatalogAPIView,
    SandboxTestAPIView,
    LiveTracesAPIView,
)

urlpatterns = [
    # Tab 1: Predictive Anomaly & Failure Prevention
    path('overview/', TelemetryOverviewAPIView.as_view(), name='telemetry-overview'),
    path('synthetic-probe/', TelemetrySyntheticRunAPIView.as_view(), name='telemetry-synthetic-probe'),
    path('anomalies/resolve/', TelemetryResolveAnomalyAPIView.as_view(), name='telemetry-resolve-anomaly'),
    path('anomalies/simulate/', SimulateAnomalyAPIView.as_view(), name='telemetry-simulate-anomaly'),
    path('prober/toggle/', ProberToggleAPIView.as_view(), name='telemetry-prober-toggle'),

    # Tab 2: 100% Backend API Catalog & Live Sandbox Matrix
    path('endpoints/', EndpointsCatalogAPIView.as_view(), name='telemetry-endpoints-catalog'),
    path('sandbox-test/', SandboxTestAPIView.as_view(), name='telemetry-sandbox-test'),

    # Tab 3: Live Request Traces & Multi-Tenant Audit Logs
    path('logs/', LiveTracesAPIView.as_view(), name='telemetry-live-traces'),
]

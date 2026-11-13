# core/telemetry_views.py
"""
Super Admin Telemetry APM Dashboard Views.
Provides real-time metric snapshots, anomaly resolutions, synthetic canary triggers,
100% API catalog static inspection, interactive sandbox executions, and live request traces.
Protected exclusively for Super Admin role.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from core.telemetry import (
    get_telemetry_summary,
    resolve_anomaly,
    run_synthetic_canary_probes,
    simulate_anomaly,
    get_live_request_traces,
    execute_sandbox_test,
    get_prober_status,
    toggle_prober,
    discover_all_registered_api_endpoints,
)


def ensure_superadmin(user):
    """Enforces that caller is an active Super Admin."""
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    is_super = (
        getattr(user, "is_superuser", False)
        or getattr(user, "role", "") == "super_admin"
        or (
            hasattr(user, "employee_profile")
            and getattr(user.employee_profile, "role", "") in ["super_admin", "admin"]
            and getattr(user.employee_profile, "is_admin", False)
        )
    )
    if not is_super:
        raise PermissionDenied("Access restricted exclusively to Super Administrators.")


class TelemetryOverviewAPIView(APIView):
    """
    GET /api/v1/superadmin/telemetry/overview/
    Returns real-time APM metrics, health score, active anomalies, and endpoint statistics.
    Supports ?platform=WEB|MOBILE|ALL and ?tenant=<tenant_id>.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_superadmin(request.user)
        platform = request.query_params.get("platform", "ALL")
        tenant = request.query_params.get("tenant", "all")
        include_catalog = request.query_params.get("include_catalog", "false").lower() in ["true", "1"]
        data = get_telemetry_summary(platform=platform, tenant_id=tenant, include_catalog=include_catalog)
        return Response({"status": "success", "data": data})


class TelemetrySyntheticRunAPIView(APIView):
    """
    POST /api/v1/superadmin/telemetry/synthetic-probe/
    Triggers an autonomous synthetic canary probe across all registered tenants,
    evaluating endpoints under both WEB and MOBILE client profiles.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_superadmin(request.user)
        report = run_synthetic_canary_probes()
        return Response({"status": "success", "canaryReport": report})


class TelemetryResolveAnomalyAPIView(APIView):
    """
    POST /api/v1/superadmin/telemetry/anomalies/resolve/
    Dismisses or resolves an identified anomaly from the active alert queue.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_superadmin(request.user)
        anomaly_id = request.data.get("anomaly_id") or request.data.get("anomalyId") or request.data.get("id")
        if not anomaly_id:
            return Response({"status": "error", "message": "anomalyId is required"}, status=400)
        found = resolve_anomaly(anomaly_id)
        return Response({"status": "success", "resolved": found, "anomalyId": anomaly_id})


class SimulateAnomalyAPIView(APIView):
    """
    POST /api/v1/superadmin/telemetry/anomalies/simulate/
    Injects a synthetic anomaly (LATENCY_SPIKE, N_PLUS_ONE_SURGE, SERVER_EXCEPTION_5XX).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_superadmin(request.user)
        anomaly_type = request.data.get("type", "LATENCY_SPIKE")
        endpoint = request.data.get("endpoint", "/api/payroll/calculate-arrears/")
        platform = request.data.get("platform", "WEB")
        anomaly = simulate_anomaly(anomaly_type=anomaly_type, endpoint=endpoint, platform=platform)
        return Response({"status": "success", "anomaly": anomaly})


class ProberToggleAPIView(APIView):
    """
    GET/POST /api/v1/superadmin/telemetry/prober/toggle/
    Controls and queries the 5-second autonomous prober daemon thread.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_superadmin(request.user)
        status = get_prober_status()
        return Response({"status": "success", "prober": status})

    def post(self, request):
        ensure_superadmin(request.user)
        enable = bool(request.data.get("enable", True))
        status = toggle_prober(enable)
        return Response({"status": "success", "prober": status})


class EndpointsCatalogAPIView(APIView):
    """
    GET /api/v1/superadmin/telemetry/endpoints/
    Returns complete static inspection catalog of all product API endpoints.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_superadmin(request.user)
        catalog = discover_all_registered_api_endpoints()
        return Response({
            "status": "success",
            "total": len(catalog),
            "endpoints": catalog,
        })


class SandboxTestAPIView(APIView):
    """
    POST /api/v1/superadmin/telemetry/sandbox-test/
    Executes a synthetic API call inside the APM sandbox.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_superadmin(request.user)
        method = request.data.get("method", "GET")
        endpoint = request.data.get("endpoint", "/api/employees/")
        payload = request.data.get("payload", {})
        tenant_id = request.data.get("tenant_id") or request.data.get("tenantId")

        result = execute_sandbox_test(
            method=method,
            endpoint=endpoint,
            payload=payload,
            tenant_id=tenant_id,
        )
        return Response({"status": "success", "result": result})


class LiveTracesAPIView(APIView):
    """
    GET /api/v1/superadmin/telemetry/logs/
    Returns filtered and paginated real-time request traces.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_superadmin(request.user)
        tenant_id = request.query_params.get("tenant", "all")
        level = request.query_params.get("level", "ALL")
        platform = request.query_params.get("platform", "ALL")
        search = request.query_params.get("search", "")
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", request.query_params.get("pageSize", 30)))

        hide_heartbeats = request.query_params.get("hide_heartbeats", "false").lower() in ["true", "1"]
        data = get_live_request_traces(
            tenant_id=tenant_id,
            level=level,
            platform=platform,
            search=search,
            hide_heartbeats=hide_heartbeats,
            page=page,
            page_size=page_size,
        )
        return Response({"status": "success", "data": data})

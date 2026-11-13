# core/middleware.py
"""
ApiTelemetryMiddleware:
High-resolution passive request profiler and telemetry feeder.

- Captures execution duration (ms) using time.perf_counter()
- Measures executed database queries using connection.execute_wrapper(QueryCounter())
- Identifies calling platform (WEB API vs MOBILE API)
- Extracts view function name and file:line source location
- Attributed to authenticated tenant and actor
- Zero third-party overhead; fail-safe containment
"""

import time
import os
import re
import json
import uuid
import logging
from django.db import connection
from core.telemetry import (
    record_request_telemetry,
    detect_client_platform,
    clean_route_pattern,
    record_live_request_trace,
)

logger = logging.getLogger("core.telemetry")


class QueryCounter:
    """Cursor execution wrapper to count queries without requiring DEBUG=True."""

    def __init__(self):
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        return execute(sql, params, many, context)


class ApiTelemetryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # Skip static assets, media files, favicons, and APM dashboard telemetry polling itself
        if (
            path.startswith(("/static/", "/media/", "/favicon.ico", "/api/media/"))
            or path.startswith("/api/v1/superadmin/telemetry/")
            or path == "/favicon.ico"
        ):
            return self.get_response(request)

        # 1. Start high-resolution monotonic timer & DB query wrapper
        start_time = time.perf_counter()
        query_counter = QueryCounter()

        # Pre-capture login credentials upfront so actor attribution is never missed
        pre_actor_email = ""
        if path.startswith("/api/auth/") and request.method == "POST":
            try:
                raw_bytes = request.body
                if raw_bytes:
                    p_data = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
                    if isinstance(p_data, dict):
                        pre_actor_email = p_data.get("email") or p_data.get("username") or ""
            except Exception:
                pass

        response = None
        error_msg = ""

        try:
            with connection.execute_wrapper(query_counter):
                response = self.get_response(request)
        except Exception as e:
            error_msg = str(e)
            raise e
        finally:
            # 2. Compute execution duration
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            query_count = query_counter.count
            status_code = response.status_code if response is not None else 500

            # 3. Extract view name, file:line source location & canonical route pattern
            view_name = "unknown_view"
            file_source = "unknown_file:0"
            canonical_endpoint = path

            resolver = getattr(request, "resolver_match", None)
            if resolver:
                view_name = getattr(resolver, "view_name", "view")
                route_pat = getattr(resolver, "route", None)
                if route_pat:
                    canonical_endpoint = clean_route_pattern(route_pat)
                func = getattr(resolver, "func", None)
                if func and hasattr(func, "__code__"):
                    code = func.__code__
                    file_source = f"{os.path.basename(code.co_filename)}:{code.co_firstlineno}"
                elif hasattr(func, "cls"):
                    cls_obj = func.cls
                    if hasattr(cls_obj, "__module__"):
                        file_source = f"{cls_obj.__module__}.{cls_obj.__name__}"

            if canonical_endpoint == path:
                # Fallback: clean parameterized dynamic segments (UUIDs, numbers)
                canonical_endpoint = re.sub(r"/[0-9a-fA-F-]{36}/", "/:id/", path)
                canonical_endpoint = re.sub(r"/\d+/", "/:id/", canonical_endpoint)

            # 4. Resolve Tenant and Actor attribution
            tenant_id = "system"
            actor_email = ""
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                actor_email = getattr(user, "email", "") or getattr(user, "username", "")
                if getattr(user, "is_superuser", False) or getattr(user, "role", "") == "super_admin":
                    tenant_id = "superadmin"
                else:
                    emp = getattr(user, "employee_profile", None)
                    if emp:
                        if getattr(emp, "organization_id", None):
                            tenant_id = f"org_{emp.organization_id}"
                        elif getattr(emp, "entity_id", None):
                            tenant_id = f"entity_{emp.entity_id}"
                        elif getattr(emp, "site_id", None):
                            tenant_id = f"site_{emp.site_id}"

            # Fallback for unauthenticated or auth-in-progress endpoints (e.g. login / token)
            if not actor_email and pre_actor_email:
                actor_email = pre_actor_email

            if not actor_email:
                try:
                    body_raw = getattr(request, "_body", None)
                    if body_raw:
                        p_data = json.loads(body_raw.decode("utf-8", errors="ignore"))
                        if isinstance(p_data, dict):
                            actor_email = p_data.get("email") or p_data.get("username") or ""
                except Exception:
                    pass
                if not actor_email and hasattr(request, "POST"):
                    actor_email = request.POST.get("email") or request.POST.get("username") or ""

            if actor_email and (tenant_id == "system" or not tenant_id):
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    matched_user = User.objects.filter(email=actor_email).first() or User.objects.filter(username=actor_email).first()
                    if matched_user:
                        if getattr(matched_user, "is_superuser", False) or getattr(matched_user, "role", "") == "super_admin":
                            tenant_id = "superadmin"
                        else:
                            emp = getattr(matched_user, "employee_profile", None)
                            if emp:
                                if getattr(emp, "organization_id", None):
                                    tenant_id = f"org_{emp.organization_id}"
                                elif getattr(emp, "entity_id", None):
                                    tenant_id = f"entity_{emp.entity_id}"
                                elif getattr(emp, "site_id", None):
                                    tenant_id = f"site_{emp.site_id}"
                except Exception:
                    pass

            # 5. Detect Client Platform (WEB vs MOBILE API) and Heartbeat
            platform = detect_client_platform(request)
            client_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "127.0.0.1")
            is_heartbeat = path.startswith("/api/notifications/") or path == "/favicon.ico"

            # 6. Record sample into Telemetry Anomaly Engine and Live Traces
            try:
                record_request_telemetry(
                    endpoint=canonical_endpoint,
                    method=request.method,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    query_count=query_count,
                    view_name=view_name,
                    file_source=file_source,
                    tenant_id=tenant_id,
                    actor_email=actor_email,
                    ip=client_ip,
                    platform=platform,
                    error_message=error_msg,
                )

                corr_id = request.META.get("HTTP_X_CORRELATION_ID") or f"corr-{uuid.uuid4().hex[:12]}"
                trace_entry = {
                    "id": f"trace-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
                    "correlationId": corr_id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "method": request.method,
                    "endpoint": path,
                    "canonicalEndpoint": canonical_endpoint,
                    "statusCode": status_code,
                    "durationMs": duration_ms,
                    "queryCount": query_count,
                    "platform": platform,
                    "tenantId": tenant_id,
                    "actorEmail": actor_email or "anonymous",
                    "clientIp": client_ip,
                    "userAgent": request.META.get("HTTP_USER_AGENT", "Unknown"),
                    "viewName": view_name,
                    "fileSource": file_source,
                    "isHeartbeat": is_heartbeat,
                    "errorMessage": error_msg or None,
                    "headers": {
                        "User-Agent": request.META.get("HTTP_USER_AGENT", "Unknown"),
                        "Content-Type": request.META.get("CONTENT_TYPE", "application/json"),
                        "X-Client-Platform": platform,
                        "Authorization": "Bearer ***" if "HTTP_AUTHORIZATION" in request.META else "None",
                    },
                    "queryParams": dict(request.GET.items()),
                }
                record_live_request_trace(trace_entry)
            except Exception as tel_err:
                logger.warning(f"Telemetry recording error (non-fatal): {tel_err}")

        return response


import os, django, time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from core.telemetry import get_telemetry_summary, get_live_request_traces

# First call
t0 = time.perf_counter()
summary1 = get_telemetry_summary()
t1 = time.perf_counter()
print(f"Call 1 get_telemetry_summary took: {(t1 - t0)*1000:.2f} ms")

# Second call
t2 = time.perf_counter()
summary2 = get_telemetry_summary()
t3 = time.perf_counter()
print(f"Call 2 get_telemetry_summary took: {(t3 - t2)*1000:.2f} ms")

# Third call
t4 = time.perf_counter()
summary3 = get_telemetry_summary()
t5 = time.perf_counter()
print(f"Call 3 get_telemetry_summary took: {(t5 - t4)*1000:.2f} ms")

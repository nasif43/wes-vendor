import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger("telemetry")

class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        
        # We can also attach a simple timing dict to the request state
        request.state.timings = {"start": start_time}
        
        response = await call_next(request)
        
        process_time = time.perf_counter() - start_time
        process_time_ms = round(process_time * 1000, 2)
        
        # Add Server-Timing header for Chrome DevTools
        server_timing = f"total;dur={process_time_ms};desc=\"Total Request Time\""
        if hasattr(request.state, "db_time"):
            db_ms = round(request.state.db_time * 1000, 2)
            server_timing += f", db;dur={db_ms};desc=\"Database Queries\""
            
        response.headers["Server-Timing"] = server_timing
        response.headers["X-Process-Time"] = str(process_time)
        
        # Log it for Vercel/Server logs
        logger.info(
            f"METHOD={request.method} PATH={request.url.path} "
            f"STATUS={response.status_code} TIME_MS={process_time_ms}"
        )
        
        return response

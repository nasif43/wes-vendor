import time
from sqlalchemy import event
from sqlalchemy.engine import Engine
import logging

logger = logging.getLogger("telemetry.db")

def attach_db_telemetry(engine):
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault('query_start_time', []).append(time.perf_counter())

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_time = conn.info['query_start_time'].pop(-1)
        total_time = time.perf_counter() - start_time
        
        # We can log slow queries
        if total_time > 0.5:
            logger.warning(f"SLOW QUERY ({round(total_time*1000, 2)}ms): {statement}")

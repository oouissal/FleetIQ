import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
os.environ["PYSPARK_PYTHON"] = sys.executable

try:
    from datetime import datetime, timedelta, timezone

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    from streaming.spark.streaming_job import with_validation

    BASE = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(3):
        ts = BASE + timedelta(seconds=10 * i)
        rows.append({
            "event_id": f"tele-{i:06d}", "vehicle_id": f"V{i + 1:05d}",
            "driver_id": f"D{i + 1:05d}", "route_id": "R001",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "speed_kmh": 50.0, "fuel_rate_lph": 8.0, "fuel_level_pct": 90.0,
            "engine_load_pct": 40.0, "engine_temp_c": 88.0,
            "ambient_temp_c": 20.0, "mileage_km": 1000.0, "idle_time_s": 0.0,
            "dt_seconds": 10, "weather": "clear", "traffic_multiplier": 1.2,
            "event_type": "telemetry",
        })
    rows[0]["speed_kmh"] = -5.0
    s = (SparkSession.builder.master("local[2]").appName("dbg4")
         .config("spark.ui.enabled", "false").getOrCreate())
    df = s.createDataFrame(rows)
    from streaming.spark.validation import rule_expressions

    fails = [F.when(~F.expr(e), F.lit(n)) for n, e in rule_expressions("telemetry").items()]
    v = df.withColumn("fails", F.array(*fails))
    v = v.withColumn("fails2", F.array_remove(F.array(*fails), F.lit(None)))
    lines = ["total=%d" % v.count()]
    lines.append("schema=%s" % v.schema.simpleString())
    for r in v.collect():
        lines.append("row_speed=%s fails=%r fails2=%r"
                     % (r["speed_kmh"], r["fails"], r["fails2"]))
    s.stop()
    open("val_debug.txt", "w").write("\n".join(lines))
except Exception:
    open("val_debug.txt", "w").write(traceback.format_exc())
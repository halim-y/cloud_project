import os
import time
from google.cloud import bigquery

GCP_PROJECT = os.environ.get("GCP_PROJECT", "acoustic-rider-487915-s8")
BQ_TABLE    = f"{GCP_PROJECT}.cloud_project.weather-records"

client = bigquery.Client(project=GCP_PROJECT)

_latest_cache      = None
_latest_cache_time = 0.0
_LATEST_TTL        = 120  # 2 min — fresh enough for announcements


def insert_row(data):
    global _latest_cache, _latest_cache_time
    _latest_cache = None   # invalidate so next read sees the new row
    _latest_cache_time = 0.0
    return client.insert_rows_json(BQ_TABLE, [data])


def get_latest_row():
    global _latest_cache, _latest_cache_time
    if _latest_cache is not None and time.time() - _latest_cache_time < _LATEST_TTL:
        return _latest_cache
    query = f"""
        SELECT indoor_temp, indoor_humidity, air_quality_tvoc, air_quality_eco2,
               outdoor_temp, outdoor_humidity, outdoor_weather, date, time
        FROM `{BQ_TABLE}`
        WHERE indoor_temp IS NOT NULL
        ORDER BY date DESC, time DESC
        LIMIT 1
    """
    rows = list(client.query(query).result())
    if not rows:
        return None
    r = rows[0]
    result = {
        "indoor_temp":      r.indoor_temp,
        "indoor_humidity":  r.indoor_humidity,
        "air_quality_tvoc": r.air_quality_tvoc,
        "air_quality_eco2": r.air_quality_eco2,
        "outdoor_temp":     r.outdoor_temp,
        "outdoor_humidity": r.outdoor_humidity,
        "outdoor_weather":  r.outdoor_weather,
        "date":             str(r.date),
        "time":             str(r.time),
    }
    _latest_cache      = result
    _latest_cache_time = time.time()
    return result

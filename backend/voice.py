import os
from google import genai
from google.genai import types
from google.cloud.bigquery import QueryJobConfig
from database import client as _bq, BQ_TABLE, GCP_PROJECT
from weather import (
    get_forecast as _fetch_forecast,
    parse_daily_forecast,
    parse_hourly_today,
)

GCP_LOCATION = os.environ.get("GCP_LOCATION", "europe-west1")
MODEL        = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

gen_client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)


SCHEMA_DOC = f"""
You answer natural-language questions about a home weather station by querying
one BigQuery table.

Table: `{BQ_TABLE}`
Columns:
  date              DATE    sensor reading date
  time              TIME    sensor reading time
  indoor_temp       FLOAT   indoor temperature, celsius
  indoor_humidity   FLOAT   indoor relative humidity, percent (0-100)
  air_quality_tvoc  FLOAT   volatile organics, ppb. <150 excellent, 150-300 good,
                            300-500 moderate, >500 poor
  air_quality_eco2  FLOAT   equivalent CO2, ppm. <700 excellent, 700-1000 good,
                            1000-1500 moderate, >1500 poor
  outdoor_temp      FLOAT   outdoor temperature, celsius (from OpenWeather)
  outdoor_humidity  FLOAT   outdoor humidity, percent
  outdoor_weather   STRING  short text e.g. "broken clouds", "rain", "clear sky"

Readings arrive every 5 minutes. Use BigQuery Standard SQL.

CRITICAL — `date` and `time` are TWO SEPARATE columns:
  • `date` is type DATE (YYYY-MM-DD), stored in LOCAL time (Europe/Zurich).
  • `time` is type TIME (HH:MM:SS), NOT a timestamp.

Patterns to use:
  • Chronological ordering: ORDER BY date DESC, time DESC
  • Latest reading:        ORDER BY date DESC, time DESC LIMIT 1
  • Today's data:          WHERE date = CURRENT_DATE("Europe/Zurich")
  • Yesterday's data:      WHERE date = DATE_SUB(CURRENT_DATE("Europe/Zurich"), INTERVAL 1 DAY)
  • Hour-of-day grouping:  GROUP BY EXTRACT(HOUR FROM time)
  • Time-of-day filter:    WHERE time BETWEEN '08:00:00' AND '09:00:00'

NEVER pass `time` alone to UNIX_SECONDS, TIMESTAMP_DIFF, or any function that
expects a TIMESTAMP — `time` is just a clock value with no date. If you truly
need a real timestamp, build one with TIMESTAMP(DATETIME(date, time),
"Europe/Zurich").
"""

SYSTEM_INSTRUCTION = f"""You are a friendly voice assistant for a home IoT weather
station. Keep answers short and conversational — one or two sentences, suitable
for being spoken aloud. Round numbers to one decimal place and always include
units (°C, %, ppb, ppm).

{SCHEMA_DOC}

You have two tools:

  • `run_query` — for any LOGGED sensor data in BigQuery. Readings arrive every
    5 minutes, so the LATEST row IS the current indoor/outdoor state. Use this
    for "right now" / "current" (get the latest row with ORDER BY date DESC,
    time DESC LIMIT 1), as well as "yesterday", "this week", "last 3 days",
    trends, averages — anything already measured. Only SELECT/WITH queries.

  • `get_forecast` — for FUTURE outdoor weather not yet measured
    (e.g. "is it going to rain later", "do I need an umbrella",
    "what's the weather tomorrow", "this afternoon's forecast"). Returns a
    5-day daily forecast and today's hourly forecast.

If a question covers both (e.g. "what's the weather today" — current state +
later forecast), call both tools and combine. If the data is missing, say so
plainly. If a question is not about the home environment or weather, politely
decline.

Examples to guide tool choice:
  • "What's the weather today?" → call BOTH `run_query` (latest row for
    current state) AND `get_forecast` (rest of today's hourly), combine
    into one short answer.
  • "Was it warmer yesterday than today?" → two `run_query` calls (or one
    with CASE / two subqueries), then compare.
  • "Is the temperature rising?" → `run_query` ORDER BY date DESC,
    time DESC LIMIT 6, infer the direction.
  • "What time does CO2 usually peak?" → `run_query` GROUP BY hour, ORDER
    BY AVG(air_quality_eco2) DESC LIMIT 1.

When the user asks a follow-up like "and yesterday?" or "what about humidity?",
resolve the pronoun/subject from the preceding turns in this conversation
before choosing a tool.
"""


_FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
              "ALTER", "MERGE", "TRUNCATE", "GRANT", "REVOKE")


def _run_query(sql: str):
    sql_clean = (sql or "").strip().rstrip(";")
    upper = sql_clean.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return {"error": "Only SELECT/WITH queries are allowed."}
    if any(kw in upper for kw in _FORBIDDEN):
        return {"error": "Forbidden keyword in query."}
    if BQ_TABLE not in sql_clean:
        return {"error": f"Query must reference the {BQ_TABLE} table only."}

    job_config = QueryJobConfig(
        use_query_cache=True,
        maximum_bytes_billed=100 * 1024 * 1024,  # 100 MB safety cap
    )
    rows = list(_bq.query(sql_clean, job_config=job_config).result(max_results=200))
    out = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return {"rows": out, "row_count": len(out)}


def _get_forecast():
    try:
        raw = _fetch_forecast()
        return {
            "daily":        parse_daily_forecast(raw),
            "hourly_today": parse_hourly_today(raw),
        }
    except Exception as e:
        return {"error": f"forecast unavailable: {str(e)[:80]}"}


_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="run_query",
        description="Read-only BigQuery query against logged sensor history. "
                    "Use for past data (yesterday, last week, trends).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "sql": types.Schema(
                    type="STRING",
                    description="A BigQuery Standard SQL SELECT or WITH query."
                ),
            },
            required=["sql"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_forecast",
        description="Live outdoor weather forecast (5-day daily + today's "
                    "hourly) from OpenWeather. Use for future weather "
                    "(today, tomorrow, this week, umbrella, rain coming).",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
])


MAX_HISTORY_TURNS = 6  # most recent N messages (user + assistant) used as context


def _history_to_contents(history):
    """Convert a list of {role, content} dicts into Gemini Content objects.
    Gemini uses 'model' for assistant turns and requires the first turn in
    `contents` to be from the user — so we drop any leading model-role
    messages (e.g. announcements that happened before the first question)."""
    out = []
    if not history:
        return out
    for msg in history[-MAX_HISTORY_TURNS:]:
        role    = "model" if msg.get("role") == "assistant" else "user"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        out.append({"role": role, "content": content})

    # Strip leading model turns — Gemini rejects history that starts with one.
    while out and out[0]["role"] == "model":
        out.pop(0)

    return [
        types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])])
        for m in out
    ]


def process_voice_query(text: str, history=None) -> str:
    if not text or not text.strip():
        return "I didn't catch that — could you ask again?"

    contents = _history_to_contents(history)
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[_TOOLS],
        temperature=0.2,
    )

    for _ in range(4):
        resp = gen_client.models.generate_content(model=MODEL, contents=contents, config=config)
        if not resp.candidates:
            return "Sorry, I couldn't come up with an answer."

        cand_content = resp.candidates[0].content
        parts = cand_content.parts or []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not calls:
            answer = (resp.text or "").strip()
            return answer or "Sorry, I don't have an answer for that."

        contents.append(cand_content)
        for fc in calls:
            args = dict(fc.args or {})
            if fc.name == "run_query":
                result = _run_query(args.get("sql", ""))
            elif fc.name == "get_forecast":
                result = _get_forecast()
            else:
                result = {"error": f"unknown tool: {fc.name}"}
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=fc.name, response=result)
            ]))

    return "Sorry, I got stuck working that out. Try rephrasing your question."

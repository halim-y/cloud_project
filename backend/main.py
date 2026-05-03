from flask import Flask, request, jsonify
import os
from google.cloud import bigquery
import requests

GCP_PROJECT         = "acoustic-rider-487915-s8"
BQ_TABLE            = f"{GCP_PROJECT}.cloud_project.weather-records"
PASSWORD_HASH       = os.environ.get("PASSWORD_HASH", "f4f263e439cf40925e6a412387a9472a6773c2580212a4fb50d224d3a817de17")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
CITY                = os.environ.get("CITY", "Genève")

client = bigquery.Client(project=GCP_PROJECT)
app = Flask(__name__)


def _fetch_outdoor_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    return {
        "outdoor_temp":     round(float(body["main"]["temp"]), 1),
        "outdoor_humidity": round(float(body["main"]["humidity"]), 1),
        "outdoor_weather":  body["weather"][0]["description"],
    }


@app.route("/send-to-bigquery", methods=["POST"])
def send_to_bigquery():
    body = request.get_json(force=True)
    if body.get("passwd") != PASSWORD_HASH:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = body["values"]
    data.update(_fetch_outdoor_weather())

    errors = client.insert_rows_json(BQ_TABLE, [data])
    if errors:
        return jsonify({"status": "error", "errors": errors}), 500

    return jsonify({"status": "success", "data": data})


@app.route("/get_outdoor_weather", methods=["POST"])
def get_outdoor_weather():
    body = request.get_json(force=True)
    if body.get("passwd") != PASSWORD_HASH:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    query = f"""
        SELECT outdoor_temp, outdoor_humidity, outdoor_weather
        FROM `{BQ_TABLE}`
        WHERE outdoor_temp IS NOT NULL
        ORDER BY date DESC, time DESC
        LIMIT 1
    """
    rows = list(client.query(query).result())
    if not rows:
        return jsonify({"status": "error", "message": "No data in database"}), 404

    row = rows[0]
    return jsonify({
        "status":           "success",
        "outdoor_temp":     row.outdoor_temp,
        "outdoor_humidity": row.outdoor_humidity,
        "outdoor_weather":  row.outdoor_weather,
    })


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "IoT Weather Backend"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)

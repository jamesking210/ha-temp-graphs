import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")

HA_URL = os.getenv("HA_URL", "http://192.168.1.3:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "changeme")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))
DB_PATH = os.getenv("DB_PATH", "/app/data/temps.sqlite3")
PORT = int(os.getenv("PORT", "8090"))

MAX_POINTS_PER_SENSOR = int(os.getenv("MAX_POINTS_PER_SENSOR", "1200"))

SENSORS = [
    {
        "key": "outside",
        "label": os.getenv("OUTSIDE_LABEL", "Outside Weather"),
        "entity_id": os.getenv("OUTSIDE_ENTITY_ID", "weather.home"),
        "value_source": os.getenv("OUTSIDE_VALUE_SOURCE", "attributes.temperature"),
    },
    {
        "key": "hallway",
        "label": os.getenv("HALLWAY_LABEL", "Public Hallway"),
        "entity_id": os.getenv("HALLWAY_ENTITY_ID", "sensor.public_hallway_temp_sensor_temperature"),
        "value_source": os.getenv("HALLWAY_VALUE_SOURCE", "state"),
    },
]

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


def utc_now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def sql_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace(" ", "T") + "Z"


def db_connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                sensor_key TEXT NOT NULL,
                label TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                raw_state TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts_utc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_sensor_ts ON readings(sensor_key, ts_utc)")


def get_nested_value(data: dict, value_source: str):
    if value_source == "state":
        return data.get("state")

    current = data
    for part in value_source.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def parse_float(value):
    if value is None:
        return None

    if isinstance(value, str) and value.lower() in {"unknown", "unavailable", "none", ""}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_entity(entity_id: str) -> dict:
    if not HA_TOKEN or HA_TOKEN == "changeme":
        raise RuntimeError("HA_TOKEN is missing. Edit .env and add a Home Assistant long-lived access token.")

    response = requests.get(
        f"{HA_URL}/api/states/{entity_id}",
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def unit_from_ha(data: dict) -> str:
    attrs = data.get("attributes", {}) or {}
    return (
        attrs.get("unit_of_measurement")
        or attrs.get("temperature_unit")
        or attrs.get("unit")
        or "°F"
    )


def poll_once():
    init_db()
    ts = utc_now_sql()
    results = []

    with db_connect() as conn:
        for sensor in SENSORS:
            try:
                data = fetch_entity(sensor["entity_id"])
                raw_value = get_nested_value(data, sensor["value_source"])
                value = parse_float(raw_value)
                unit = unit_from_ha(data)

                if value is None:
                    results.append({**sensor, "ok": False, "error": f"Value was not numeric: {raw_value}", "ts": sql_to_iso(ts)})
                    continue

                conn.execute(
                    """
                    INSERT INTO readings (ts_utc, sensor_key, label, entity_id, value, unit, raw_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ts, sensor["key"], sensor["label"], sensor["entity_id"], value, unit, str(data.get("state"))),
                )

                results.append({**sensor, "ok": True, "value": value, "unit": unit, "ts": sql_to_iso(ts)})
            except Exception as exc:
                results.append({**sensor, "ok": False, "error": str(exc), "ts": sql_to_iso(ts)})

    return results


def choose_bucket_seconds(hours: int) -> int:
    total_seconds = max(1, hours * 3600)
    raw_bucket = math.ceil(total_seconds / MAX_POINTS_PER_SENSOR)

    friendly = [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]

    for bucket in friendly:
        if raw_bucket <= bucket:
            return bucket

    return 86400


def poll_loop():
    time.sleep(3)

    while True:
        results = poll_once()
        for result in results:
            if result.get("ok"):
                print(f"[{result['ts']}] {result['label']}: {result['value']}{result.get('unit', '')}", flush=True)
            else:
                print(f"[{result['ts']}] Poll error for {result['entity_id']}: {result.get('error')}", flush=True)
        time.sleep(POLL_SECONDS)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/config")
def api_config():
    return jsonify({"ha_url": HA_URL, "poll_seconds": POLL_SECONDS, "sensors": SENSORS, "max_points_per_sensor": MAX_POINTS_PER_SENSOR})


@app.route("/api/poll", methods=["POST"])
def api_poll():
    return jsonify({"results": poll_once()})


@app.route("/api/latest")
def api_latest():
    init_db()
    latest = []

    with db_connect() as conn:
        for sensor in SENSORS:
            row = conn.execute(
                """
                SELECT ts_utc, sensor_key, label, entity_id, value, unit
                FROM readings
                WHERE sensor_key = ?
                ORDER BY ts_utc DESC, id DESC
                LIMIT 1
                """,
                (sensor["key"],),
            ).fetchone()

            if row:
                item = dict(row)
                item["ts"] = sql_to_iso(item.pop("ts_utc"))
                latest.append(item)
            else:
                latest.append({"sensor_key": sensor["key"], "label": sensor["label"], "entity_id": sensor["entity_id"], "value": None, "unit": "°F", "ts": None})

    return jsonify({"latest": latest})


@app.route("/api/history")
def api_history():
    init_db()

    hours = request.args.get("hours", default=24, type=int)
    hours = max(1, min(hours, 24 * 365 * 3))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_sql = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    bucket_seconds = choose_bucket_seconds(hours)

    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT
                datetime((CAST(strftime('%s', ts_utc) AS INTEGER) / ?) * ?, 'unixepoch') AS bucket_ts_utc,
                sensor_key,
                label,
                entity_id,
                AVG(value) AS value,
                unit,
                COUNT(*) AS samples
            FROM readings
            WHERE ts_utc >= ?
            GROUP BY sensor_key, bucket_ts_utc
            ORDER BY bucket_ts_utc ASC, sensor_key ASC
            """,
            (bucket_seconds, bucket_seconds, cutoff_sql),
        ).fetchall()

    readings = []
    for row in rows:
        item = dict(row)
        item["ts"] = sql_to_iso(item.pop("bucket_ts_utc"))
        readings.append(item)

    return jsonify({"hours": hours, "bucket_seconds": bucket_seconds, "readings": readings})


@app.route("/health")
def health():
    return jsonify({"ok": True})


init_db()
threading.Thread(target=poll_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

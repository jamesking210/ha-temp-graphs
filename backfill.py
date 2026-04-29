import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def load_dotenv_if_present():
    """Tiny .env loader so this works both inside Docker and directly on linuxbox1."""
    env_path = os.path.join(APP_DIR, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_dotenv_if_present()

HA_URL = os.getenv("HA_URL", "http://192.168.1.3:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "changeme")
DB_PATH = os.getenv("DB_PATH", "/app/data/temps.sqlite3")

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


def parse_dt(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    # Date only, e.g. 2026-04-01
    if "T" not in value and " " not in value:
        value = value + "T00:00:00"

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_to_ha_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def dt_to_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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


def unit_from_ha(data: dict) -> str:
    attrs = data.get("attributes", {}) or {}
    return attrs.get("unit_of_measurement") or attrs.get("temperature_unit") or attrs.get("unit") or "°F"


def fetch_history(entity_id: str, start: datetime, end: datetime):
    if not HA_TOKEN or HA_TOKEN == "changeme":
        raise RuntimeError("HA_TOKEN is missing. Edit .env and add a Home Assistant long-lived access token.")

    url = f"{HA_URL}/api/history/period/{dt_to_ha_iso(start)}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": dt_to_ha_iso(end),
    }

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        params=params,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def reading_exists(conn, sensor_key: str, ts_utc: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM readings WHERE sensor_key = ? AND ts_utc = ? LIMIT 1",
        (sensor_key, ts_utc),
    ).fetchone()
    return row is not None


def insert_history_records(sensor: dict, history_payload) -> dict:
    inserted = 0
    skipped_existing = 0
    skipped_bad = 0

    if not history_payload:
        return {"inserted": inserted, "skipped_existing": skipped_existing, "skipped_bad": skipped_bad}

    # Home Assistant returns a list of entity history lists.
    entity_records = history_payload[0] if isinstance(history_payload, list) and history_payload else []

    with db_connect() as conn:
        for item in entity_records:
            raw_value = get_nested_value(item, sensor["value_source"])
            value = parse_float(raw_value)
            if value is None:
                skipped_bad += 1
                continue

            raw_ts = item.get("last_updated") or item.get("last_changed")
            if not raw_ts:
                skipped_bad += 1
                continue

            try:
                ts_utc = dt_to_sql(parse_dt(raw_ts))
            except ValueError:
                skipped_bad += 1
                continue

            if reading_exists(conn, sensor["key"], ts_utc):
                skipped_existing += 1
                continue

            conn.execute(
                """
                INSERT INTO readings (ts_utc, sensor_key, label, entity_id, value, unit, raw_state)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_utc,
                    sensor["key"],
                    sensor["label"],
                    sensor["entity_id"],
                    value,
                    unit_from_ha(item),
                    str(item.get("state")),
                ),
            )
            inserted += 1

    return {"inserted": inserted, "skipped_existing": skipped_existing, "skipped_bad": skipped_bad}


def chunk_ranges(start: datetime, end: datetime, chunk_hours: int):
    current = start
    delta = timedelta(hours=chunk_hours)
    while current < end:
        chunk_end = min(current + delta, end)
        yield current, chunk_end
        current = chunk_end


def main():
    parser = argparse.ArgumentParser(description="Backfill Home Assistant temperature history into the dashboard SQLite database.")
    parser.add_argument("--days", type=float, default=10, help="How many days back to import. Default: 10")
    parser.add_argument("--start", help="Optional start timestamp, e.g. 2026-04-01 or 2026-04-01T00:00:00-05:00")
    parser.add_argument("--end", help="Optional end timestamp. Default: now")
    parser.add_argument("--chunk-hours", type=int, default=24, help="Fetch this many hours per API call. Default: 24")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between API calls. Default: 0.5")
    args = parser.parse_args()

    init_db()

    end = parse_dt(args.end) if args.end else datetime.now(timezone.utc)
    start = parse_dt(args.start) if args.start else end - timedelta(days=args.days)

    if start >= end:
        print("ERROR: start must be before end", file=sys.stderr)
        sys.exit(1)

    print(f"Home Assistant: {HA_URL}")
    print(f"Database: {DB_PATH}")
    print(f"Backfill range: {dt_to_ha_iso(start)} to {dt_to_ha_iso(end)}")
    print(f"Chunk size: {args.chunk_hours} hours")
    print()

    totals = {}

    for sensor in SENSORS:
        print(f"=== {sensor['label']} ({sensor['entity_id']}) ===")
        totals[sensor["key"]] = {"inserted": 0, "skipped_existing": 0, "skipped_bad": 0}

        for chunk_start, chunk_end in chunk_ranges(start, end, args.chunk_hours):
            print(f"Fetching {dt_to_ha_iso(chunk_start)} to {dt_to_ha_iso(chunk_end)} ...", end=" ", flush=True)
            try:
                payload = fetch_history(sensor["entity_id"], chunk_start, chunk_end)
                result = insert_history_records(sensor, payload)
                for key in totals[sensor["key"]]:
                    totals[sensor["key"]][key] += result[key]
                print(f"inserted={result['inserted']} existing={result['skipped_existing']} bad={result['skipped_bad']}")
            except Exception as exc:
                print(f"ERROR: {exc}")

            time.sleep(args.sleep)

        print()

    print("Done.")
    for sensor in SENSORS:
        total = totals[sensor["key"]]
        print(f"{sensor['label']}: inserted={total['inserted']} existing={total['skipped_existing']} bad={total['skipped_bad']}")


if __name__ == "__main__":
    main()

# Home Assistant Temperature Graphs

A simple no-login Docker dashboard for graphing Home Assistant temperature data over time.

Built for tracking:

- `weather.home` outside temperature from `attributes.temperature`
- `sensor.public_hallway_temp_sensor_temperature` hallway temperature from the sensor state

The app polls Home Assistant on a schedule, stores readings in SQLite, and serves a dark themed web dashboard with graphs.

## What it does

- Runs in Docker / Docker Compose
- Talks to Home Assistant using the REST API
- Stores history locally in `./data/temps.sqlite3`
- Serves a no-login website on port `8090`
- Includes 6 hour, 24 hour, 7 day, and 30 day graph views
- Has a manual **Poll Now** button

## Home Assistant token

In Home Assistant:

1. Click your user profile in the lower left.
2. Scroll to **Long-Lived Access Tokens**.
3. Create a new token.
4. Copy it into your `.env` file.

Do not commit your real `.env` file to GitHub.

## Deploy on linuxbox1

```bash
git clone https://github.com/jamesking210/ha-temp-graphs.git
cd ha-temp-graphs
cp .env.example .env
nano .env
```

Edit this:

```env
HA_URL=http://192.168.1.3:8123
HA_TOKEN=paste_your_home_assistant_long_lived_token_here
```

Start it:

```bash
docker compose up -d --build
```

Open it:

```text
http://192.168.1.5:8090
```

Or:

```text
http://linuxbox1:8090
```

## Update later

```bash
cd ~/ha-temp-graphs
git pull
docker compose up -d --build
```

## Check logs

```bash
docker logs -f ha-temp-graphs
```

## Test Home Assistant from linuxbox1

```bash
source .env
curl -s \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  "$HA_URL/api/states/weather.home" | python3 -m json.tool
```

Then test the hallway sensor:

```bash
source .env
curl -s \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  "$HA_URL/api/states/sensor.public_hallway_temp_sensor_temperature" | python3 -m json.tool
```

## Environment variables

| Variable | Default | Notes |
|---|---:|---|
| `HA_URL` | `http://192.168.1.3:8123` | Home Assistant URL |
| `HA_TOKEN` | blank | Required long-lived access token |
| `PORT` | `8090` | App port inside container |
| `POLL_SECONDS` | `300` | Poll interval in seconds |
| `DB_PATH` | `/app/data/temps.sqlite3` | SQLite database path |
| `OUTSIDE_ENTITY_ID` | `weather.home` | Outside temperature source |
| `OUTSIDE_VALUE_SOURCE` | `attributes.temperature` | Pulls temperature from weather attributes |
| `HALLWAY_ENTITY_ID` | `sensor.public_hallway_temp_sensor_temperature` | Hallway temperature sensor |
| `HALLWAY_VALUE_SOURCE` | `state` | Pulls temperature from sensor state |

## Notes

This dashboard has no login. Keep it on your LAN unless you put it behind authentication, a VPN, or a trusted reverse proxy.

# Home Assistant Temperature Graphs

A simple no-login Docker dashboard for graphing Home Assistant temperature data over time.

Built for tracking:

- `weather.home` outside temperature from `attributes.temperature`
- `sensor.public_hallway_temp_sensor_temperature` hallway temperature from the sensor state

The app polls Home Assistant on a schedule, stores readings in SQLite, and serves a dark themed web dashboard with card-style boxes and a large trend graph.

## What it does

- Runs in Docker / Docker Compose
- Talks to Home Assistant using the REST API
- Stores history locally in `/opt/ha-temp-graphs/data/temps.sqlite3`
- Serves a no-login website on port `8090`
- Shows top boxes for:
  - Current weather outside
  - Current public hallway temperature
- Shows a larger temperature trend graph with ranges:
  - 24 hours
  - 3 days
  - 1 month
  - 3 months
  - 6 months
  - 9 months
  - 1 year
  - 1.5 years
  - 2 years
- Has a manual **Poll Home Assistant Now** button

## Recommended folder layout

This project is meant to live under `/opt`, like a normal self-hosted service:

```text
/opt/ha-temp-graphs/
├── app.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env
├── .env.example
├── data/
│   └── temps.sqlite3
└── static/
    ├── index.html
    ├── styles.css
    └── app.js
```

The database is stored in:

```text
/opt/ha-temp-graphs/data/temps.sqlite3
```

## Home Assistant token

In Home Assistant:

1. Click your user profile in the lower left.
2. Scroll to **Long-Lived Access Tokens**.
3. Create a new token.
4. Copy it into your `.env` file.

Do not commit your real `.env` file to GitHub.

## Deploy on linuxbox1 using `/opt`

SSH into linuxbox1, then run:

```bash
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
cd /opt
git clone https://github.com/jamesking210/ha-temp-graphs.git
cd /opt/ha-temp-graphs
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
cd /opt/ha-temp-graphs
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

## If `/opt` already has root-owned folders

If you prefer not to make your whole `/opt` folder owned by your user, do this instead:

```bash
sudo mkdir -p /opt/ha-temp-graphs
sudo chown -R "$USER":"$USER" /opt/ha-temp-graphs
git clone https://github.com/jamesking210/ha-temp-graphs.git /opt/ha-temp-graphs
cd /opt/ha-temp-graphs
cp .env.example .env
nano .env
docker compose up -d --build
```

## Update later

```bash
cd /opt/ha-temp-graphs
git pull
docker compose up -d --build
```

## Restart

```bash
cd /opt/ha-temp-graphs
docker compose restart
```

## Stop

```bash
cd /opt/ha-temp-graphs
docker compose down
```

## Check logs

```bash
docker logs -f ha-temp-graphs
```

Or:

```bash
cd /opt/ha-temp-graphs
docker compose logs -f
```

## Test Home Assistant from linuxbox1

```bash
cd /opt/ha-temp-graphs
source .env
curl -s \
  -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  "$HA_URL/api/states/weather.home" | python3 -m json.tool
```

Then test the hallway sensor:

```bash
cd /opt/ha-temp-graphs
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
| `HA_TOKEN` | `changeme` | Required long-lived access token |
| `PORT` | `8090` | App port inside container |
| `POLL_SECONDS` | `300` | Poll interval in seconds |
| `DB_PATH` | `/app/data/temps.sqlite3` | SQLite database path inside the container |
| `MAX_POINTS_PER_SENSOR` | `1200` | Limits chart points for long date ranges |
| `OUTSIDE_ENTITY_ID` | `weather.home` | Outside temperature source |
| `OUTSIDE_VALUE_SOURCE` | `attributes.temperature` | Pulls temperature from weather attributes |
| `OUTSIDE_LABEL` | `Outside Weather` | Display label |
| `HALLWAY_ENTITY_ID` | `sensor.public_hallway_temp_sensor_temperature` | Hallway temperature sensor |
| `HALLWAY_VALUE_SOURCE` | `state` | Pulls temperature from sensor state |
| `HALLWAY_LABEL` | `Public Hallway` | Display label |

## Port

The app uses host port `8090` by default:

```yaml
ports:
  - "8090:8090"
```

If you need to change it, edit `docker-compose.yml` and change the left side:

```yaml
ports:
  - "8091:8090"
```

Then open:

```text
http://192.168.1.5:8091
```

## Notes

This dashboard has no login. Keep it on your LAN unless you put it behind authentication, a VPN, or a trusted reverse proxy.

The graph page uses Chart.js from a public CDN, so the browser viewing the dashboard needs internet access. Home Assistant polling and SQLite storage stay local on your network.

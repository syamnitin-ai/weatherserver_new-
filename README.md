# Weather API

This project exposes the Weather MCP tools over HTTP using FastAPI.

## Run locally

1. Set your environment variable:

```powershell
$env:SERPAPI_API_KEY = "your_serpapi_api_key"
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Start the app:

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

4. Browse endpoints:

- `GET /healthz`
- `GET /weather/current?city=London`
- `GET /weather/forecast?city=London`
- `GET /weather/travel?city=London`
- `GET /weather/aqi?city=London`
- `GET /weather/sunrise-sunset?city=London`
- `GET /weather/photo-spots?city=London`
- `GET /weather/events?city=London`

## Deploy on Render

1. Create a new Render web service.
2. Point Render to this repository.
3. Use the following settings:
   - Environment: `Python`
   - Build Command: `cd weather && pip install -r requirements.txt`
   - Start Command: `cd weather && uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/healthz`
4. Add the environment variable `SERPAPI_API_KEY` in Render.

## Notes

- The app loads `.env` automatically if present, but Render should use the deployed environment variable.
- The existing `weather.py` file is still usable as an MCP tool server; this app adds HTTP deployment support.

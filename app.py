import os
from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv

import weather as weather_module

load_dotenv()

app = FastAPI(
    title="Weather API",
    description="HTTP wrapper around the Weather MCP toolset for deployment on Render.",
    version="0.1.0",
)


def _require_city(city: str) -> str:
    if not city or not city.strip():
        raise HTTPException(status_code=422, detail="The city parameter is required.")
    return city.strip()


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "Weather API is running."}


@app.get("/healthz", tags=["root"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/weather/current", tags=["weather"])
async def current_weather(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_current_weather(city)}


@app.get("/weather/forecast", tags=["weather"])
async def forecast(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_weather_forecast(city)}


@app.get("/weather/travel", tags=["weather"])
async def travel_plan(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_travel_plan(city)}


@app.get("/weather/aqi", tags=["weather"])
async def aqi(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_aqi(city)}


@app.get("/weather/sunrise-sunset", tags=["weather"])
async def sunrise_sunset(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_sunrise_sunset(city)}


@app.get("/weather/photo-spots", tags=["weather"])
async def photo_spots(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_photo_spots(city)}


@app.get("/weather/events", tags=["weather"])
async def local_events(city: str = Query(..., description="City name", examples={"city": {"summary": "Example city", "value": "London"}})) -> dict[str, str]:
    city = _require_city(city)
    return {"result": await weather_module.get_local_events(city)}


import os
import sys
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load .env file so SERPAPI_API_KEY is available
load_dotenv()

# Initialize FastMCP server — the name shows up in Claude Desktop
mcp = FastMCP("weather")

# Constants
SERPAPI_BASE = "https://serpapi.com/search.json"
SERPAPI_KEY  = os.getenv("SERPAPI_API_KEY", "")
USER_AGENT   = "weather-app/1.0"


# ── Helper: call SerpApi ─────────────────────────────────────────
async def fetch_serpapi(query: str) -> dict[str, Any] | None:
    """
    Send a search query to SerpApi and return the parsed JSON.
    SerpApi scrapes Google and returns structured data including
    the weather answer box when you search 'weather in <city>'.
    """
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "engine": "google",
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(SERPAPI_BASE, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"SerpApi request failed: {e}", file=sys.stderr)
            return None


# ── Tool 1: Current weather ──────────────────────────────────────
@mcp.tool()
async def get_current_weather(city: str) -> str:
    """
    Get the current weather for any city in the world.
    Returns temperature, humidity, wind speed, precipitation,
    and weather condition. Uses Google's live weather data via SerpApi.

    Args:
        city: The city name to get weather for, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"weather in {city}")

    if not data:
        return f"Error: Could not connect to SerpApi. Check your API key and internet connection."

    answer = data.get("answer_box", {})

    # SerpApi puts current weather inside answer_box with type "weather_result"
    if answer.get("type") != "weather_result":
        return f"Could not find live weather for '{city}'. Try a more specific city name, e.g. 'Mumbai, India'."

    result = f"""
Current Weather — {answer.get('location', city)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Condition     : {answer.get('weather', 'N/A')}
Temperature   : {answer.get('temperature', 'N/A')}° {answer.get('unit', 'F')}
Humidity      : {answer.get('humidity', 'N/A')}
Wind          : {answer.get('wind', 'N/A')}
Precipitation : {answer.get('precipitation', 'N/A')}
As of         : {answer.get('date', 'N/A')}
""".strip()

    return result


# ── Tool 2: Multi-day forecast ───────────────────────────────────
@mcp.tool()
async def get_weather_forecast(city: str) -> str:
    """
    Get a multi-day weather forecast for any city in the world.
    Returns daily high/low temperatures, conditions, humidity,
    wind speed, and precipitation chance for each day.

    Args:
        city: The city name to get the forecast for, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"weather in {city}")

    if not data:
        return "Error: Could not connect to SerpApi. Check your API key."

    answer = data.get("answer_box", {})

    if answer.get("type") != "weather_result":
        return f"Could not find forecast for '{city}'. Try a more specific name."

    forecast = answer.get("forecast", [])
    if not forecast:
        return f"No forecast data found for '{city}'."

    unit = answer.get("unit", "F")
    location = answer.get("location", city)

    lines = []
    for day in forecast:
        temp = day.get("temperature", {})
        lines.append(
            f"{day.get('day', '?'):12} | "
            f"{day.get('weather', 'N/A'):20} | "
            f"High: {temp.get('high', '?')}°{unit}  Low: {temp.get('low', '?')}°{unit} | "
            f"Humidity: {day.get('humidity', 'N/A')} | "
            f"Rain: {day.get('precipitation', 'N/A')}"
        )

    header = f"Forecast for {location}\n{'━' * 90}"
    return header + "\n" + "\n".join(lines)


# ── Run the server ───────────────────────────────────────────────
if __name__ == "__main__":
    # IMPORTANT: Never use print() here — it writes to stdout and
    # corrupts the JSON-RPC messages Claude sends over stdio.
    # Always use sys.stderr for any debug logging.
    print("Weather MCP Server starting...", file=sys.stderr)
    mcp.run(transport="stdio")


import os
import re
import sys
from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load .env file so SERPAPI_API_KEY is available
load_dotenv()

# Initialize FastMCP server — the name shows up in Claude Desktop
# Bind to Render's host/port when deployed; defaults remain local-safe.
PORT = int(os.getenv("PORT", "8000"))
mcp = FastMCP("weather", host="0.0.0.0", port=PORT)

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


def _collect_strings(node: Any) -> list[str]:
    """Collect all string leaves from nested JSON-like objects."""
    strings: list[str] = []
    if isinstance(node, str):
        strings.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            strings.extend(_collect_strings(value))
    elif isinstance(node, list):
        for value in node:
            strings.extend(_collect_strings(value))
    return strings


def _find_first_value(node: Any, keys: set[str]) -> str | None:
    """Find the first non-empty value for matching keys in nested data."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in keys and value not in (None, ""):
                return str(value)
            found = _find_first_value(value, keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_value(item, keys)
            if found:
                return found
    return None


def _extract_aqi_from_text(text: str) -> str | None:
    """Extract numeric AQI value from free text."""
    patterns = [
        r"\bAQI\s*[:\-]?\s*(\d{1,3})\b",
        r"\bAir Quality Index\s*[:\-]?\s*(\d{1,3})\b",
        r"\bUS AQI\s*[:\-]?\s*(\d{1,3})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_status_from_text(text: str) -> str | None:
    """Extract AQI status phrase from free text."""
    statuses = [
        "Good",
        "Moderate",
        "Poor",
        "Unhealthy for Sensitive Groups",
        "Unhealthy",
        "Very Unhealthy",
        "Hazardous",
    ]
    lower_text = text.lower()
    for status in statuses:
        if status.lower() in lower_text:
            return status
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


# ── Tool 3: Air Quality Index ─────────────────────────────────────
@mcp.tool()
async def get_aqi(city: str) -> str:
    """
    Get Air Quality Index (AQI) details for a city.
    Returns AQI value, status category, PM2.5, PM10, and basic health advice.

    Args:
        city: The city name to get AQI for, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"air quality index {city}")
    if not data:
        return "Error: Could not connect to SerpApi. Check your API key and internet connection."

    answer = data.get("answer_box", {}) or {}
    local_results = data.get("local_results", []) or []

    # Search across full payload because AQI can be in different paths per region/query.
    search_space: dict[str, Any] = {
        "answer_box": answer,
        "knowledge_graph": data.get("knowledge_graph", {}),
        "local_results": local_results,
        "organic_results": data.get("organic_results", []) or [],
    }

    aqi_value = (
        _find_first_value(search_space, {"aqi", "value", "aqi_value", "us_aqi"})
        or _find_first_value(search_space, {"current_aqi", "air_quality_index"})
        or "N/A"
    )
    status = _find_first_value(search_space, {"status", "category", "quality"}) or "Unknown"
    pm25 = _find_first_value(search_space, {"pm25", "pm2.5", "pm_2_5"}) or "N/A"
    pm10 = _find_first_value(search_space, {"pm10", "pm_10"}) or "N/A"

    # Final fallback: parse snippets/text for AQI/status if structured fields are missing.
    if aqi_value == "N/A" or status == "Unknown":
        all_text = " ".join(_collect_strings(search_space))
        if aqi_value == "N/A":
            parsed_aqi = _extract_aqi_from_text(all_text)
            if parsed_aqi:
                aqi_value = parsed_aqi
        if status == "Unknown":
            parsed_status = _extract_status_from_text(all_text)
            if parsed_status:
                status = parsed_status

    recommendation = "Good - Suitable for normal outdoor activities."
    status_l = str(status).lower()
    if "hazardous" in status_l:
        recommendation = "Hazardous - Avoid outdoor exposure; use air purifier and mask."
    elif "very unhealthy" in status_l:
        recommendation = "Very Unhealthy - Stay indoors as much as possible."
    elif "unhealthy" in status_l:
        recommendation = "Unhealthy - Reduce prolonged outdoor exertion."
    elif "poor" in status_l:
        recommendation = "Poor - Use N95 mask outdoors and limit heavy activity."
    elif "moderate" in status_l:
        recommendation = "Moderate - Sensitive groups should limit outdoor time."

    return f"""
Air Quality Index — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AQI Value      : {aqi_value}
Status         : {status}
PM2.5          : {pm25}
PM10           : {pm10}

Health Advice:
{recommendation}
""".strip()


# ── Tool 4: Best tourist spots ────────────────────────────────────
@mcp.tool()
async def get_best_tourist_spots(city: str) -> str:
    """
    Get the best tourist spots in a city.
    Returns a short ranked list of attractions with practical visiting tips.

    Args:
        city: The city name to discover places in, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"best tourist spots in {city}")
    if not data:
        return "Error: Could not connect to SerpApi. Check your API key and internet connection."

    places: list[str] = []

    local_results = data.get("local_results", []) or []
    for item in local_results[:7]:
        name = item.get("title") or item.get("name")
        if name:
            places.append(str(name).strip())

    if not places:
        organic_results = data.get("organic_results", []) or []
        for item in organic_results[:7]:
            title = item.get("title")
            if title:
                places.append(str(title).strip())

    if not places:
        return f"Could not find tourist spot results for '{city}'. Try a more specific location like '{city}, India'."

    # De-duplicate while keeping order.
    seen: set[str] = set()
    unique_places: list[str] = []
    for place in places:
        key = place.lower()
        if key not in seen:
            seen.add(key)
            unique_places.append(place)

    top_places = unique_places[:5]
    place_lines = "\n".join(f"{idx}. {name}" for idx, name in enumerate(top_places, start=1))

    return f"""
Best Tourist Spots — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Top recommendations:
{place_lines}

Tips:
- Visit popular landmarks early morning to avoid crowds.
- Keep at least one indoor attraction as backup for bad weather.
- Check official timings and ticket details before visiting.
""".strip()


# ── Run the server ───────────────────────────────────────────────
if __name__ == "__main__":
    # IMPORTANT: Never use print() here — it writes to stdout and
    # corrupts the JSON-RPC messages Claude sends over stdio.
    # Always use sys.stderr for any debug logging.
    if os.getenv("RENDER") or os.getenv("PORT"):
        print(f"Weather MCP Server starting on HTTP transport at 0.0.0.0:{PORT}", file=sys.stderr)
        mcp.run(transport="streamable-http")
    else:
        print("Weather MCP Server starting on stdio transport", file=sys.stderr)
        mcp.run(transport="stdio")

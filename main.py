
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


def _extract_numeric(text: str) -> str | None:
    """Return first 1-3 digit number found in text."""
    match = re.search(r"\b(\d{1,3})\b", text)
    if match:
        return match.group(1)
    return None


def _normalize_aqi_value(value: Any) -> str | None:
    """Normalize AQI value to numeric string when possible."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return str(number) if 0 <= number <= 500 else None
    text = str(value).strip()
    numeric = _extract_numeric(text)
    if numeric is None:
        return None
    number = int(numeric)
    return numeric if 0 <= number <= 500 else None


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


def _looks_like_article_heading(title: str) -> bool:
    """Filter out blog/article/listing-style headings."""
    lowered = title.lower()
    blocked_terms = [
        "things to do",
        "best things",
        "top places",
        "must-visit",
        "what are some",
        "tourist places",
        "guide",
        "itinerary",
        "in 2026",
        "blog",
        "tripadvisor",
        "wikipedia",
    ]
    return any(term in lowered for term in blocked_terms)


def _best_visit_time_for_place(place_name: str) -> str:
    """Return a practical best-time window based on place type."""
    name = place_name.lower()
    if any(word in name for word in ["temple", "gurudwara", "church", "mosque", "shrine"]):
        return "6:00 AM - 9:00 AM (peaceful hours, fewer queues)"
    if any(word in name for word in ["park", "garden", "lake", "beach", "waterfall", "fort"]):
        return "6:30 AM - 10:00 AM or 4:30 PM - 6:30 PM (pleasant weather)"
    if any(word in name for word in ["museum", "gallery", "planetarium", "science"]):
        return "11:00 AM - 2:00 PM (ideal indoor timing)"
    if any(word in name for word in ["mall", "market", "bazaar", "street", "plaza"]):
        return "5:00 PM - 8:30 PM (best atmosphere and shopping)"
    if any(word in name for word in ["zoo", "safari", "bird"]):
        return "8:00 AM - 11:00 AM (animals most active)"
    if any(word in name for word in ["amusement", "theme park", "water park"]):
        return "10:00 AM - 1:00 PM and 4:00 PM - 7:00 PM"
    return "8:00 AM - 11:00 AM or 5:00 PM - 7:00 PM (generally best for sightseeing)"


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

    aqi_raw = (
        _find_first_value(search_space, {"aqi", "value", "aqi_value", "us_aqi"})
        or _find_first_value(search_space, {"current_aqi", "air_quality_index"})
    )
    aqi_value = _normalize_aqi_value(aqi_raw) or "N/A"
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

    # If status was captured as a number-like value, convert it to proper status.
    if status != "Unknown":
        status_numeric = _normalize_aqi_value(status)
        if status_numeric:
            status = "Unknown"

    # Backfill missing status from AQI number bands.
    if status == "Unknown":
        aqi_num = _normalize_aqi_value(aqi_value)
        if aqi_num is not None:
            value = int(aqi_num)
            if value <= 50:
                status = "Good"
            elif value <= 100:
                status = "Moderate"
            elif value <= 150:
                status = "Unhealthy for Sensitive Groups"
            elif value <= 200:
                status = "Unhealthy"
            elif value <= 300:
                status = "Very Unhealthy"
            else:
                status = "Hazardous"

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
    queries = [
        f"top attractions in {city}",
        f"famous places to visit in {city}",
        f"must visit landmarks in {city}",
    ]

    all_places: list[str] = []

    for query in queries:
        data = await fetch_serpapi(query)
        if not data:
            continue

        local_results = data.get("local_results", []) or []
        for item in local_results[:10]:
            name = item.get("title") or item.get("name")
            if name:
                clean_name = str(name).strip()
                if not _looks_like_article_heading(clean_name):
                    all_places.append(clean_name)

        organic_results = data.get("organic_results", []) or []
        for item in organic_results[:10]:
            title = item.get("title")
            if title:
                clean_title = str(title).strip()
                if not _looks_like_article_heading(clean_title):
                    all_places.append(clean_title)

    if not all_places:
        return (
            f"Could not find structured tourist places for '{city}' right now. "
            f"Try a more specific location like '{city}, India'."
        )

    seen: set[str] = set()
    unique_places: list[str] = []
    for place in all_places:
        normalized = re.sub(r"\s+\|.*$", "", place).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_places.append(re.sub(r"\s+\|.*$", "", place).strip())

    top_places = unique_places[:6]
    if not top_places:
        return f"Could not extract specific tourist spots for '{city}'."

    place_lines = "\n".join(
        f"{idx}. {name}\n   Best time: {_best_visit_time_for_place(name)}"
        for idx, name in enumerate(top_places, start=1)
    )

    return f"""
Best Tourist Spots — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recommended places and best timings:
{place_lines}

Planning note:
- Weekdays are usually less crowded than weekends.
- Recheck official opening hours before travel.
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

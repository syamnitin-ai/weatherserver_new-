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


def _parse_temperature(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.+-]", "", value)
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _temperature_celsius(value: Any, unit: str = "F") -> str:
    temp = _parse_temperature(value)
    if temp is None:
        return "N/A"

    if unit.upper() == "C":
        celsius = temp
    else:
        celsius = (temp - 32) * 5.0 / 9.0

    if abs(celsius - round(celsius)) < 0.05:
        return f"{round(celsius)}"
    return f"{celsius:.1f}"


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

    unit = answer.get('unit', 'F')
    temperature_c = _temperature_celsius(answer.get('temperature'), unit)

    result = f"""
Current Weather — {answer.get('location', city)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Condition     : {answer.get('weather', 'N/A')}
Temperature   : {temperature_c}°C
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
        high_c = _temperature_celsius(temp.get("high"), unit)
        low_c = _temperature_celsius(temp.get("low"), unit)
        lines.append(
            f"{day.get('day', '?'):12} | "
            f"{day.get('weather', 'N/A'):20} | "
            f"High: {high_c}°C  Low: {low_c}°C | "
            f"Humidity: {day.get('humidity', 'N/A')} | "
            f"Rain: {day.get('precipitation', 'N/A')}"
        )

    header = f"Forecast for {location}\n{'━' * 90}"
    return header + "\n" + "\n".join(lines)


# ── Tool 3: Travel planning ──────────────────────────────────────

@mcp.tool()
async def get_travel_plan(city: str) -> str:
    """
    Suggest a short travel plan for a location.
    Returns recommended places to visit in the city and suggested timing blocks.

    Args:
        city: The city or destination to plan for, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"best places to visit in {city}")
    if not data:
        return "Error: Could not connect to SerpApi. Check your API key and internet connection."

    answer = data.get("answer_box", {})
    location = answer.get("title") or city
    description = answer.get("description") or answer.get("snippet") or answer.get("answer") or ""

    places = []
    local_results = data.get("local_results", []) or []
    for item in local_results[:5]:
        name = item.get("title") or item.get("name")
        if name:
            places.append(name)

    if not places:
        for result in data.get("organic_results", [])[:5]:
            title = result.get("title")
            if title:
                cleaned = re.sub(r"\s+\|.*", "", title)
                places.append(cleaned)

    if not places and description:
        places = [part.strip() for part in re.split(r"[;,\n]", description) if len(part.strip()) > 10][:5]

    if not places:
        places = [f"Popular sightseeing spots in {city}", "Local market or food street", "Museum or cultural center", "City park or viewpoint"]

    morning = places[0] if len(places) > 0 else "Main sight"
    late_morning = places[1] if len(places) > 1 else "Nearby cultural site"
    afternoon = places[2] if len(places) > 2 else "Lunch and museum"
    evening = places[3] if len(places) > 3 else "City market or waterfront"
    night = places[4] if len(places) > 4 else "Dinner and local evening activity"

    return f"""
Travel Plan — {location}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recommended places:
1. {morning}
2. {late_morning}
3. {afternoon}
4. {evening}
5. {night}

Suggested timing:
- Morning (08:00 – 11:00): Start with the top landmark or best outdoor attraction.
- Late morning (11:00 – 13:00): Visit a nearby museum, palace, or cultural site.
- Afternoon (13:00 – 16:00): Have lunch and explore a market, garden, or indoor attraction.
- Evening (16:00 – 19:00): Enjoy a scenic spot, waterfront, viewpoint, or park.
- Night (19:00 – 21:00): Finish with dinner, local food streets, or an evening entertainment area.

Notes:
- Adjust based on local opening hours and weather.
- If you want more details, ask for specific attractions, dining, or transit tips in {city}.
""".strip()


# ── Tool 4: Air Quality Index ────────────────────────────────────────────────────────────

@mcp.tool()
async def get_aqi(city: str) -> str:
    """
    Get the Air Quality Index (AQI) and pollution levels for a city.
    Returns current air quality status, PM2.5, PM10, and health recommendations.

    Args:
        city: The city name to get AQI for, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"air quality index {city}")
    
    if not data:
        return "Error: Could not connect to SerpApi. Check your API key and internet connection."

    answer = data.get("answer_box", {})
    
    if not answer:
        answer = {}
        local = data.get("local_results", [])
        if local:
            answer = local[0]
    
    aqi_value = answer.get("value") or answer.get("aqi") or "N/A"
    status = answer.get("status") or "Unknown"
    pm25 = answer.get("pm25") or answer.get("PM2.5") or "N/A"
    pm10 = answer.get("pm10") or answer.get("PM10") or "N/A"
    
    recommendation = "Good - Suitable for all outdoor activities"
    if isinstance(status, str):
        if "poor" in status.lower():
            recommendation = "Poor - Avoid outdoor activities, use N95 masks"
        elif "unhealthy" in status.lower():
            recommendation = "Unhealthy - Stay indoors, especially vulnerable groups"
        elif "moderate" in status.lower():
            recommendation = "Moderate - Sensitive groups should limit outdoor activity"
        elif "good" in status.lower():
            recommendation = "Good - Suitable for all outdoor activities"
    
    return f"""
Air Quality Index — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AQI Value     : {aqi_value}
Status        : {status}
PM2.5         : {pm25}
PM10          : {pm10}

Health Tips:
{recommendation}

- Consider indoor activities if AQI is poor or unhealthy
- Wear N95 masks for outdoor activities if AQI > 150
- Check real-time updates before planning outdoor travel
""".strip()


# ── Tool 5: Sunrise & Sunset Times ───────────────────────────────────────────────────────

@mcp.tool()
async def get_sunrise_sunset(city: str) -> str:
    """
    Get sunrise and sunset times for a city.
    Useful for planning photography, outdoor activities, and evening plans.

    Args:
        city: The city name, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"sunrise sunset time {city}")
    
    if not data:
        return "Error: Could not connect to SerpApi."

    answer = data.get("answer_box", {})
    
    sunrise = answer.get("sunrise") or "N/A"
    sunset = answer.get("sunset") or "N/A"
    day_length = answer.get("day_length") or "N/A"
    
    if sunrise == "N/A":
        organic = data.get("organic_results", [])
        if organic:
            snippet = organic[0].get("snippet", "")
            if "sunrise" in snippet.lower():
                lines = snippet.split("\n")
                for line in lines:
                    if "sunrise" in line.lower():
                        sunrise = line
                    if "sunset" in line.lower():
                        sunset = line
    
    return f"""
Sunrise & Sunset — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sunrise       : {sunrise}
Sunset        : {sunset}
Day Length    : {day_length}

Photography Tips:
- Golden hour (1 hour after sunrise): Best for landscape photography
- Blue hour (20 minutes after sunset): Great for cityscape shots
- Plan outdoor activities during daylight hours
- Evening walks recommended 30-45 minutes before sunset
""".strip()


# ── Tool 6: Best Spots for Sunrise/Sunset ────────────────────────────────────────────────

@mcp.tool()
async def get_photo_spots(city: str) -> str:
    """
    Get the best locations in a city for sunrise and sunset photography.
    Returns viewpoints, parks, and scenic spots recommended for photography.

    Args:
        city: The city name, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"best sunrise sunset spots {city} photography viewpoint")
    
    if not data:
        return "Error: Could not connect to SerpApi."

    answer = data.get("answer_box", {})
    spots = []
    
    local_results = data.get("local_results", []) or []
    for item in local_results[:6]:
        name = item.get("title") or item.get("name")
        if name:
            spots.append(name)
    
    if not spots:
        organic = data.get("organic_results", [])
        for result in organic[:6]:
            title = result.get("title")
            if title:
                cleaned = re.sub(r"\s+\|.*", "", title)
                spots.append(cleaned)
    
    if not spots:
        spots = [
            f"Main hilltop or elevated viewpoint in {city}",
            f"Waterfront promenade or riverside in {city}",
            f"City rooftop bar or terrace cafe",
            f"Historical monument with open view",
            f"Local park or garden with scenic outlook",
            f"Beach or lake area if available"
        ]
    
    spot_list = "\n".join([f"{i+1}. {spot}" for i, spot in enumerate(spots[:6])])
    
    return f"""
Best Photo Spots — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recommended locations for sunrise/sunset:

{spot_list}

Photography Guide:
- Sunrise (30 min before to 1 hour after): Soft golden light, clear skies
- Sunset (1 hour before to 30 min after): Rich colors, dramatic skies
- Best camera settings: ISO 100-400, f/2.8-f/4, 1/125-1/500 shutter
- Golden hour produces warm, flattering light
- Arrive 30 minutes early to secure good spots
""".strip()


# ── Tool 7: Local Events ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_local_events(city: str) -> str:
    """
    Get upcoming local events, festivals, and cultural activities in a city.
    Returns current and upcoming events happening in the destination.

    Args:
        city: The city name, e.g. 'Delhi', 'Mumbai', 'London'
    """
    data = await fetch_serpapi(f"events happening in {city} festivals 2026")
    
    if not data:
        return "Error: Could not connect to SerpApi."

    events = []
    
    answer = data.get("answer_box", {})
    if answer.get("events"):
        for event in answer.get("events", [])[:5]:
            event_name = event.get("name") or event.get("title")
            if event_name:
                events.append(event_name)
    
    if not events:
        local_results = data.get("local_results", []) or []
        for item in local_results[:5]:
            name = item.get("title") or item.get("name")
            if name and ("festival" in name.lower() or "event" in name.lower() or "concert" in name.lower()):
                events.append(name)
    
    if not events:
        organic = data.get("organic_results", [])
        for result in organic[:5]:
            title = result.get("title")
            if title:
                cleaned = re.sub(r"\s+\|.*", "", title)
                events.append(cleaned)
    
    if not events:
        events = [
            f"Check local tourism board for {city} events",
            "Seasonal festivals and cultural celebrations",
            "Concert series and musical events",
            "Food festivals and culinary events",
            "Sports events and marathons"
        ]
    
    event_list = "\n".join([f"{i+1}. {event}" for i, event in enumerate(events[:5])])
    
    return f"""
Local Events & Festivals — {city}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Upcoming events:

{event_list}

Tips:
- Check exact dates and ticket availability on official websites
- Book accommodations early during major festivals
- Some events require advance registration or reservations
- Cultural festivals offer authentic local experiences
- Sports events and concerts attract large crowds

For more details, visit the city's tourism board or event-specific websites.
""".strip()


# ── Run the server ───────────────────────────────────────────────
if __name__ == "__main__":
    # IMPORTANT: Never use print() here — it writes to stdout and
    # corrupts the JSON-RPC messages Claude sends over stdio.
    # Always use sys.stderr for any debug logging.
    print("Weather MCP Server starting...", file=sys.stderr)
    mcp.run(transport="stdio")
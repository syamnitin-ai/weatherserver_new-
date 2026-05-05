
import os
import json
import re
import sys
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo
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
# Use engine="google" for weather/AQI/forecast/sun queries.
# Use engine="google_maps" for place discovery/map queries.
async def fetch_serpapi(query: str, engine: str = "google") -> dict[str, Any] | None:
    """
    Send a search query to SerpApi and return the parsed JSON.
    SerpApi scrapes Google and returns structured data including
    the weather answer box when you search 'weather in <city>'.
    """
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "engine": engine,
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


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return int(parsed)


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


def _best_visit_time_for_place(place_name: str, category: str) -> str:
    """Return a practical best-time window based on place type/category."""
    combined = f"{place_name} {category}".lower()
    if any(word in combined for word in ["temple", "gurudwara", "church", "mosque", "shrine"]):
        return "6:00 AM - 9:00 AM (peaceful hours, fewer queues)"
    if any(word in combined for word in ["park", "garden", "lake", "beach", "waterfall", "fort", "monument"]):
        return "6:30 AM - 10:00 AM or 4:30 PM - 6:30 PM (pleasant weather)"
    if any(word in combined for word in ["museum", "gallery", "planetarium", "science"]):
        return "11:00 AM - 2:00 PM (ideal indoor timing)"
    if any(word in combined for word in ["mall", "market", "bazaar", "street", "plaza"]):
        return "5:00 PM - 8:30 PM (best atmosphere and shopping)"
    if any(word in combined for word in ["zoo", "safari", "bird", "sanctuary", "wildlife"]):
        return "8:00 AM - 11:00 AM (animals most active)"
    if any(word in combined for word in ["amusement", "theme park", "water park"]):
        return "10:00 AM - 1:00 PM and 4:00 PM - 7:00 PM"
    return "8:00 AM - 11:00 AM or 5:00 PM - 7:00 PM (generally best for sightseeing)"


def _tourist_intent_score(name: str, category: str) -> int:
    """Score how likely a place is a true tourist attraction."""
    combined = f"{name} {category}".lower()
    attraction_terms = [
        "temple", "church", "mosque", "shrine", "fort", "palace", "museum",
        "gallery", "monument", "memorial", "park", "garden", "lake", "beach",
        "waterfall", "sanctuary", "zoo", "viewpoint", "cave", "island",
        "heritage", "landmark", "attraction", "planetarium", "science",
    ]
    non_tourist_terms = [
        "jewellery", "jewelry", "gold", "silver", "store", "shop", "hospital",
        "clinic", "school", "college", "bank", "atm", "salon", "spa",
        "hardware", "agency", "real estate", "wholesaler", "factory",
    ]
    score = 0
    if any(term in combined for term in attraction_terms):
        score += 4
    if any(term in combined for term in non_tourist_terms):
        score -= 6
    return score


def _place_tip(name: str, category: str) -> str:
    combined = f"{name} {category}".lower()
    if "temple" in combined or "shrine" in combined:
        return "Carry modest clothing and avoid peak prayer hours for shorter queues."
    if any(word in combined for word in ["park", "garden", "lake", "beach"]):
        return "Carry water and sunscreen; sunset hours are usually most scenic."
    if any(word in combined for word in ["museum", "gallery", "planetarium"]):
        return "Book tickets online if available to skip queue."
    if any(word in combined for word in ["sanctuary", "zoo", "wildlife"]):
        return "Visit in the morning when animal activity is highest."
    return "Visit on weekdays and check opening hours before leaving."


def _aqi_status_from_value(aqi_value: int | None) -> str:
    if aqi_value is None:
        return "Unknown"
    if aqi_value <= 50:
        return "Good"
    if aqi_value <= 100:
        return "Moderate"
    if aqi_value <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi_value <= 200:
        return "Unhealthy"
    if aqi_value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _health_advice_from_status(status: str) -> str:
    status_l = status.lower()
    if "hazardous" in status_l:
        return "Avoid outdoor exposure; use air purifier and N95 mask."
    if "very unhealthy" in status_l:
        return "Stay indoors as much as possible."
    if "unhealthy for sensitive" in status_l:
        return "Sensitive groups should avoid prolonged outdoor activity."
    if "unhealthy" in status_l:
        return "Reduce prolonged outdoor exertion."
    if "poor" in status_l:
        return "Use N95 mask outdoors and limit heavy activity."
    if "moderate" in status_l:
        return "Sensitive groups should limit outdoor time."
    return "Air quality is acceptable for most people."


def _uv_risk_from_index(uv_index: int) -> str:
    if uv_index <= 2:
        return "Low"
    if uv_index <= 5:
        return "Moderate"
    if uv_index <= 7:
        return "High"
    if uv_index <= 10:
        return "Very High"
    return "Extreme"


def _compass_from_wind_text(wind_text: str) -> str:
    if not wind_text:
        return "N"
    upper = wind_text.upper()
    for label in ["NE", "NW", "SE", "SW", "N", "E", "S", "W"]:
        if re.search(rf"\b{label}\b", upper):
            return label
    return "N"


def _condition_icon(condition: str) -> str:
    text = condition.lower()
    if "thunder" in text:
        return "⛈️"
    if "rain" in text or "drizzle" in text:
        return "🌧️"
    if "snow" in text:
        return "❄️"
    if "fog" in text or "mist" in text or "haze" in text:
        return "🌫️"
    if "cloud" in text or "overcast" in text:
        return "☁️"
    if "clear" in text or "sunny" in text:
        return "☀️"
    return "🌤️"


def _city_country_from_location(location: str, fallback_city: str) -> tuple[str, str]:
    if not location:
        return fallback_city, "Unknown"
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return location.strip(), "Unknown"


def _timezone_for_country(country: str) -> str:
    mapping = {
        "india": "Asia/Kolkata",
        "usa": "America/New_York",
        "united states": "America/New_York",
        "uk": "Europe/London",
        "united kingdom": "Europe/London",
        "uae": "Asia/Dubai",
        "australia": "Australia/Sydney",
        "canada": "America/Toronto",
    }
    return mapping.get(country.lower(), "UTC")


def _extract_aqi_fields(data: dict[str, Any]) -> tuple[int, str]:
    search_space: dict[str, Any] = {
        "answer_box": data.get("answer_box", {}) or {},
        "knowledge_graph": data.get("knowledge_graph", {}) or {},
        "local_results": data.get("local_results", []) or [],
        "organic_results": data.get("organic_results", []) or [],
    }
    aqi_raw = (
        _find_first_value(search_space, {"aqi", "value", "aqi_value", "us_aqi"})
        or _find_first_value(search_space, {"current_aqi", "air_quality_index"})
    )
    aqi_value = _to_int(_normalize_aqi_value(aqi_raw))
    status = _find_first_value(search_space, {"status", "category", "quality"}) or "Unknown"
    if aqi_value is None:
        all_text = " ".join(_collect_strings(search_space))
        parsed = _extract_aqi_from_text(all_text)
        aqi_value = _to_int(parsed)
    if aqi_value is None:
        aqi_value = 0
    if status == "Unknown" or _normalize_aqi_value(status):
        status = _aqi_status_from_value(aqi_value)
    return aqi_value, status


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
    data = await fetch_serpapi(f"weather in {city}", engine="google") or {}
    answer = data.get("answer_box", {}) or {}

    location = str(answer.get("location") or city)
    city_name, country = _city_country_from_location(location, city)
    timezone = _timezone_for_country(country)
    now_local = datetime.now(ZoneInfo(timezone))
    last_updated = now_local.isoformat(timespec="seconds")

    temp_val = _to_float(answer.get("temperature")) or 0.0
    unit = str(answer.get("unit") or "F").upper()
    if unit == "C":
        temperature_c = round(temp_val)
        temperature_f = round((temp_val * 9.0 / 5.0) + 32.0)
    else:
        temperature_f = round(temp_val)
        temperature_c = round((temp_val - 32.0) * 5.0 / 9.0)

    feels_like_c = temperature_c
    feels_like_f = temperature_f
    humidity = _to_int(answer.get("humidity")) or 0
    if humidity >= 70 and temperature_c >= 30:
        feels_like_c = temperature_c + 3
        feels_like_f = round((feels_like_c * 9.0 / 5.0) + 32.0)

    wind_text = str(answer.get("wind") or "")
    wind_speed_kmh = _to_int(wind_text) or 0
    wind_direction = _compass_from_wind_text(wind_text)

    visibility_km = _to_int(answer.get("visibility")) or 10
    uv_index = _to_int(answer.get("uv_index")) or 0
    uv_risk = _uv_risk_from_index(uv_index)
    condition = str(answer.get("weather") or "Unknown")
    icon = _condition_icon(condition)
    precipitation_mm = _to_float(answer.get("precipitation")) or 0.0
    pressure_hpa = _to_int(answer.get("pressure")) or 0
    dew_point_c = _to_int(answer.get("dew_point")) or 0
    cloud_cover_percent = _to_int(answer.get("cloud_cover")) or 0

    sun_data = await fetch_serpapi(f"sunrise sunset time {city}", engine="google") or {}
    sun_answer = sun_data.get("answer_box", {}) or {}
    sunrise = str(sun_answer.get("sunrise") or "06:00 AM")
    sunset = str(sun_answer.get("sunset") or "06:00 PM")

    carry: list[str] = []
    if uv_index > 5:
        carry.extend(["sunscreen", "water bottle"])
    if precipitation_mm > 0:
        carry.append("umbrella")
    if not carry:
        carry.append("water bottle")

    outdoor_safe = not (uv_index >= 8 or precipitation_mm > 10)
    reason = "Conditions are generally suitable for outdoor plans."
    if not outdoor_safe:
        reasons: list[str] = []
        if uv_index >= 8:
            reasons.append("UV index is very high")
        if precipitation_mm > 10:
            reasons.append("heavy rain is likely")
        reason = ". ".join(reasons) + ". Limit outdoor exposure."

    payload = {
        "city": city_name,
        "country": country,
        "timezone": timezone,
        "last_updated": last_updated,
        "current": {
            "temperature_c": temperature_c,
            "temperature_f": temperature_f,
            "feels_like_c": feels_like_c,
            "feels_like_f": feels_like_f,
            "humidity_percent": humidity,
            "wind_speed_kmh": wind_speed_kmh,
            "wind_direction": wind_direction,
            "visibility_km": visibility_km,
            "uv_index": uv_index,
            "uv_risk": uv_risk,
            "condition": condition,
            "condition_icon": icon,
            "sunrise": sunrise,
            "sunset": sunset,
            "pressure_hpa": pressure_hpa,
            "dew_point_c": dew_point_c,
            "cloud_cover_percent": cloud_cover_percent,
            "precipitation_mm": precipitation_mm,
        },
        "travel_advisory": {
            "outdoor_safe": outdoor_safe,
            "reason": reason,
            "recommended_time_outdoors": "Before 9 AM or after 6 PM" if not outdoor_safe else "Anytime except peak noon hours",
            "carry": carry,
        },
    }
    return json.dumps(payload, indent=2)


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
    data = await fetch_serpapi(f"weather in {city}", engine="google")

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
    data = await fetch_serpapi(f"air quality index {city}", engine="google")
    if not data:
        return "Error: Could not fetch AQI from SerpApi. Check SERPAPI_API_KEY and internet connection."

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
    aqi_value_str = _normalize_aqi_value(aqi_raw)
    status = _find_first_value(search_space, {"status", "category", "quality"}) or "Unknown"
    pm25_raw = _find_first_value(search_space, {"pm25", "pm2.5", "pm_2_5"})
    pm10_raw = _find_first_value(search_space, {"pm10", "pm_10"})

    # Final fallback: parse snippets/text for AQI/status if structured fields are missing.
    if aqi_value_str is None or status == "Unknown":
        all_text = " ".join(_collect_strings(search_space))
        if aqi_value_str is None:
            parsed_aqi = _extract_aqi_from_text(all_text)
            if parsed_aqi:
                aqi_value_str = parsed_aqi
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
    aqi_num = _to_int(aqi_value_str)
    if status == "Unknown":
        status = _aqi_status_from_value(aqi_num)

    pm25 = _to_float(pm25_raw)
    pm10 = _to_float(pm10_raw)

    payload = {
        "city": city,
        "aqi": aqi_num,
        "status": status,
        "pm25": pm25,
        "pm10": pm10,
        "health_advice": _health_advice_from_status(status),
        "data_quality": {
            "aqi_present": aqi_num is not None,
            "pm25_present": pm25 is not None,
            "pm10_present": pm10 is not None,
            "source": "serpapi",
        },
    }
    return json.dumps(payload, indent=2)


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
        f"tourist attractions in {city}",
        f"famous landmarks in {city}",
        f"hidden gems in {city}",
    ]

    all_candidates: list[dict[str, Any]] = []

    for query in queries:
        data = await fetch_serpapi(query, engine="google_maps")
        if not data:
            continue

        local_results = data.get("local_results", []) or []
        for item in local_results:
            name = str(item.get("title") or item.get("name") or "").strip()
            if not name or _looks_like_article_heading(name):
                continue

            category = str(item.get("type") or item.get("category") or "attraction").strip()
            intent_score = _tourist_intent_score(name, category)
            if intent_score < 0:
                continue
            address = str(item.get("address") or "N/A").strip()
            rating = _to_float(item.get("rating"))
            reviews = _to_int(item.get("reviews"))
            price = item.get("price")
            place_id = str(item.get("place_id") or item.get("data_id") or "").strip()
            phone = str(item.get("phone") or "N/A").strip()
            website = str(item.get("website") or "N/A").strip()
            hours = str(item.get("hours") or item.get("open_state") or "N/A").strip()
            photos = item.get("photos_link") or item.get("thumbnail") or None

            gps = item.get("gps_coordinates") or {}
            latitude = _to_float(gps.get("latitude"))
            longitude = _to_float(gps.get("longitude"))

            hidden_gem = bool((reviews is not None and reviews < 500) and (rating is None or rating >= 4.2))
            entry_fee = "N/A"
            if isinstance(price, str) and price.strip():
                entry_fee = price.strip()
            elif isinstance(price, (int, float)):
                entry_fee = str(price)

            place_obj = {
                "name": name,
                "category": category,
                "address": address,
                "rating": rating,
                "review_count": reviews,
                "place_id": place_id or None,
                "coordinates": {
                    "lat": latitude,
                    "lng": longitude,
                },
                "opening_hours": hours,
                "entry_fee": entry_fee,
                "best_time": _best_visit_time_for_place(name, category),
                "tip": _place_tip(name, category),
                "phone": phone,
                "website": website,
                "photos": photos,
                "hidden_gem": hidden_gem,
                "tourist_intent_score": intent_score,
            }
            all_candidates.append(place_obj)

    if not all_candidates:
        return json.dumps(
            {
                "city": city,
                "total_results": 0,
                "places": [],
                "error": "No structured place data returned from provider.",
            },
            indent=2,
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for place in all_candidates:
        key = _normalize_key(place["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(place)

    deduped.sort(
        key=lambda p: (
            -(p["tourist_intent_score"] or 0),
            p["rating"] is None,
            -((p["rating"] or 0.0) * 20.0 + min((p["review_count"] or 0), 6000) / 300.0),
        )
    )
    top_places = deduped[:10]

    payload = {
        "city": city,
        "total_results": len(top_places),
        "places": top_places,
    }
    return json.dumps(payload, indent=2)


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

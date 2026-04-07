import os
import re
from typing import Any, Dict, List

import requests


ATTRACTION_DB: Dict[str, List[Dict[str, Any]]] = {
    "北京": [
        {"name": "故宫博物院", "type": "历史文化", "price": 60, "scene": "mixed", "description": "明清皇家宫殿，适合深度了解北京历史。"},
        {"name": "颐和园", "type": "皇家园林", "price": 30, "scene": "outdoor", "description": "湖光山色优美，适合晴天慢逛。"},
        {"name": "八达岭长城", "type": "历史文化", "price": 40, "scene": "outdoor", "description": "天气晴朗时视野开阔，体验长城气势。"},
        {"name": "中国国家博物馆", "type": "历史文化", "price": 0, "scene": "indoor", "description": "室内免费展馆，适合雨天或低预算。"},
        {"name": "南锣鼓巷", "type": "文化街区", "price": 0, "scene": "mixed", "description": "适合轻松步行，体验老北京胡同。"},
    ],
    "南京": [
        {"name": "中山陵", "type": "历史文化", "price": 0, "scene": "outdoor", "description": "近代历史地标，适合晴天步行参观。"},
        {"name": "总统府", "type": "历史文化", "price": 35, "scene": "indoor", "description": "兼具近代史展陈和园林空间，适合历史爱好者。"},
        {"name": "南京博物院", "type": "历史文化", "price": 0, "scene": "indoor", "description": "免费且馆藏丰富，适合雨天或深度文化游。"},
        {"name": "夫子庙-秦淮河", "type": "文化街区", "price": 0, "scene": "mixed", "description": "适合轻松闲逛和夜景体验。"},
        {"name": "玄武湖", "type": "自然风光", "price": 0, "scene": "outdoor", "description": "开阔湖景，适合轻松散步和低预算出行。"},
        {"name": "明孝陵", "type": "历史文化", "price": 70, "scene": "outdoor", "description": "明代皇家陵寝，历史文化氛围浓厚。"},
    ],
    "上海": [
        {"name": "上海博物馆", "type": "历史文化", "price": 0, "scene": "indoor", "description": "适合雨天和文化爱好者。"},
        {"name": "豫园", "type": "古典园林", "price": 40, "scene": "mixed", "description": "江南园林与老城厢风貌结合。"},
        {"name": "外滩", "type": "城市景观", "price": 0, "scene": "outdoor", "description": "适合轻松打卡和看城市天际线。"},
    ],
    "杭州": [
        {"name": "西湖", "type": "自然风光", "price": 0, "scene": "outdoor", "description": "晴天体验最佳，适合轻松散步。"},
        {"name": "浙江省博物馆", "type": "历史文化", "price": 0, "scene": "indoor", "description": "适合雨天和文化类出游。"},
        {"name": "灵隐寺", "type": "历史文化", "price": 75, "scene": "mixed", "description": "人文与自然结合，适合慢节奏游览。"},
    ],
}

DEFAULT_SOLD_OUT = {"故宫博物院", "总统府"}


def normalize_weather_label(weather_text: str) -> str:
    text = (weather_text or "").lower()
    if "sun" in text or "晴" in weather_text:
        return "sunny"
    if "rain" in text or "雨" in weather_text:
        return "rainy"
    if "snow" in text or "雪" in weather_text:
        return "snowy"
    if "cloud" in text or "阴" in weather_text or "多云" in weather_text:
        return "cloudy"
    return "mild"


def get_weather(city: str) -> Dict[str, Any]:
    url = f"https://wttr.in/{city}?format=j1"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        current_condition = data["current_condition"][0]
        weather_desc = current_condition["weatherDesc"][0]["value"]
        temp_c = current_condition["temp_C"]
        normalized = normalize_weather_label(weather_desc)
        summary = f"{city}当前天气:{weather_desc}，气温{temp_c}摄氏度"
        return {
            "ok": True,
            "city": city,
            "weather": weather_desc,
            "normalized_weather": normalized,
            "temp_c": temp_c,
            "summary": summary,
        }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"错误:查询天气时遇到网络问题 - {e}"}
    except (KeyError, IndexError, ValueError) as e:
        return {"ok": False, "error": f"错误:解析天气数据失败，可能是城市名称无效 - {e}"}


def _extract_budget_value(budget: str) -> int | None:
    if not budget:
        return None
    match = re.search(r"(\d+)", str(budget))
    return int(match.group(1)) if match else None


def _score_candidate(item: Dict[str, Any], normalized_weather: str, preference: str, budget_value: int | None, strategy: str) -> int:
    score = 0
    preference = preference or ""

    if preference and (preference in item["type"] or preference in item["description"]):
        score += 4
    if budget_value is not None:
        score += 2 if item["price"] <= budget_value else -3

    if normalized_weather == "sunny":
        score += 2 if item["scene"] in {"outdoor", "mixed"} else 0
    elif normalized_weather in {"rainy", "snowy"}:
        score += 3 if item["scene"] in {"indoor", "mixed"} else -2
    elif normalized_weather == "cloudy":
        score += 1 if item["scene"] == "mixed" else 0

    if strategy == "budget_first":
        score += 4 if item["price"] == 0 else 0
    elif strategy == "indoor_first":
        score += 3 if item["scene"] in {"indoor", "mixed"} else -1
    elif strategy == "light_trip":
        score += 3 if item["price"] == 0 or item["scene"] == "mixed" else 0
    elif strategy == "scenic_first":
        score += 3 if item["type"] in {"自然风光", "古典园林", "城市景观", "皇家园林"} else 0
    elif strategy == "culture_first":
        score += 3 if item["type"] == "历史文化" else 0

    return score


def get_attraction_candidates(
    city: str,
    weather: str,
    preference: str = "",
    budget: str = "",
    strategy: str = "default",
) -> Dict[str, Any]:
    candidates = ATTRACTION_DB.get(city)
    if not candidates:
        return {"ok": False, "error": f"错误: 暂不支持城市 {city} 的本地景点库。"}

    budget_value = _extract_budget_value(budget)
    normalized_weather = normalize_weather_label(weather)

    ranked: List[Dict[str, Any]] = []
    for item in candidates:
        item_copy = dict(item)
        item_copy["score"] = _score_candidate(item_copy, normalized_weather, preference, budget_value, strategy)
        ranked.append(item_copy)

    ranked.sort(key=lambda x: (x["score"], -x["price"]), reverse=True)
    top = ranked[:4]
    summary = "；".join([f"{item['name']}({item['type']}, {item['price']}元)" for item in top])
    return {
        "ok": True,
        "city": city,
        "normalized_weather": normalized_weather,
        "preference": preference,
        "budget": budget_value,
        "strategy": strategy,
        "candidates": top,
        "summary": f"候选景点: {summary}",
    }


def check_ticket_availability(attraction: str) -> Dict[str, Any]:
    sold_out_env = os.environ.get("SOLD_OUT_ATTRACTIONS", "")
    sold_out = {name.strip() for name in sold_out_env.split(",") if name.strip()}
    sold_out = sold_out or DEFAULT_SOLD_OUT

    available = attraction not in sold_out
    if available:
        return {"ok": True, "name": attraction, "available": True, "reason": "可购买或无需门票"}
    return {"ok": True, "name": attraction, "available": False, "reason": "门票已售罄"}


available_tools = {
    "get_weather": get_weather,
    "get_attraction_candidates": get_attraction_candidates,
    "check_ticket_availability": check_ticket_availability,
}

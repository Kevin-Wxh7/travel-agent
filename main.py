import os
import re
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from llm_client import OpenAICompatibleClient
from prompt import build_system_prompt
from tools import available_tools, check_ticket_availability

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "")
MODEL_ID = os.getenv("OPENAI_MODEL", "")

llm = OpenAICompatibleClient(
    model=MODEL_ID,
    api_key=API_KEY,
    base_url=BASE_URL,
)

CITY_CANDIDATES = ["北京", "南京", "上海", "杭州"]
PREFERENCE_KEYWORDS = {
    "历史文化": ["历史", "文化", "博物馆", "古迹", "人文"],
    "自然风光": ["自然", "风景", "湖", "山", "公园"],
    "文化街区": ["街区", "夜景", "逛街", "小吃"],
}


def build_initial_state() -> Dict[str, Any]:
    return {
        "memory": {
            "preferred_types": [],
            "disliked_types": [],
            "budget": None,
            "travel_style": None,
        },
        "context": {
            "city": None,
            "weather": None,
            "temp_c": None,
        },
        "recommendation": {
            "current": None,
            "candidates": [],
            "shown": [],
            "rejected_names": [],
            "rejected_count": 0,
            "rejection_reasons": [],
            "strategy": "default",
            "auto_backup_notes": [],
        },
    }


def update_memory(state: Dict[str, Any], key: str, value: str) -> str:
    memory = state["memory"]
    value = value.strip()

    if key in {"preferred_types", "preferred_type"}:
        if value and value not in memory["preferred_types"]:
            memory["preferred_types"].append(value)
        return f"已记录用户喜欢 {value} 类型景点。"

    if key in {"disliked_types", "disliked_type"}:
        if value and value not in memory["disliked_types"]:
            memory["disliked_types"].append(value)
        return f"已记录用户不喜欢 {value} 类型景点。"

    if key == "budget":
        match = re.search(r"(\d+)", value)
        memory["budget"] = int(match.group(1)) if match else value
        return f"已记录预算为 {memory['budget']}。"

    if key == "travel_style":
        memory["travel_style"] = value
        return f"已记录出行风格为 {value}。"

    memory[key] = value
    return f"已记录 {key} = {value}。"


def extract_city(text: str) -> Optional[str]:
    for city in CITY_CANDIDATES:
        if city in text:
            return city
    return None


def extract_preferences_from_text(text: str, state: Dict[str, Any]) -> list[str]:
    updates = []

    city = extract_city(text)
    if city:
        state["context"]["city"] = city

    budget_match = re.search(r"(?:预算|不超过|控制在|低于)\s*(\d+)\s*元?", text)
    if budget_match:
        updates.append(update_memory(state, "budget", budget_match.group(1)))

    if any(keyword in text for keyword in ["轻松", "休闲", "不想太累"]):
        updates.append(update_memory(state, "travel_style", "轻松"))
    if any(keyword in text for keyword in ["深度游", "深入了解", "想认真逛"]):
        updates.append(update_memory(state, "travel_style", "深度游"))

    for label, keywords in PREFERENCE_KEYWORDS.items():
        if any(k in text for k in keywords):
            if any(neg in text for neg in [f"不喜欢{keywords[0]}", f"不要{keywords[0]}"]):
                updates.append(update_memory(state, "disliked_types", label))
            else:
                updates.append(update_memory(state, "preferred_types", label))

    if "太贵" in text and state["memory"]["budget"] is None:
        updates.append(update_memory(state, "budget", "50"))

    return list(dict.fromkeys(updates))


def detect_rejection_reason(text: str) -> Optional[str]:
    rejection_markers = ["换一个", "不想去", "不要这个", "不喜欢", "不合适", "太贵", "太远", "太累", "售罄"]
    if not any(marker in text for marker in rejection_markers):
        return None
    for marker in ["太贵", "太远", "太累", "不喜欢", "售罄", "不合适", "换一个", "不想去", "不要这个"]:
        if marker in text:
            return marker
    return "用户拒绝当前推荐"


def apply_rejection_feedback(text: str, state: Dict[str, Any]) -> Optional[str]:
    reason = detect_rejection_reason(text)
    if not reason:
        return None

    rec = state["recommendation"]
    rec["rejected_count"] += 1
    rec["rejection_reasons"].append(reason)
    if rec["current"] and rec["current"]["name"] not in rec["rejected_names"]:
        rec["rejected_names"].append(rec["current"]["name"])

    if reason == "太贵" and state["memory"]["budget"] is None:
        update_memory(state, "budget", "50")
    if reason == "太累":
        update_memory(state, "travel_style", "轻松")

    if rec["rejected_count"] >= 3:
        note = reflect_and_adjust_strategy(state)
        return f"检测到连续拒绝 {rec['rejected_count']} 次。{note}"

    return f"已记录拒绝原因: {reason}。当前连续拒绝次数为 {rec['rejected_count']}。"


def reflect_and_adjust_strategy(state: Dict[str, Any]) -> str:
    rec = state["recommendation"]
    reasons = " ".join(rec["rejection_reasons"])
    memory = state["memory"]

    if "太贵" in reasons or (memory["budget"] is not None and memory["budget"] <= 50):
        rec["strategy"] = "budget_first"
    elif "太累" in reasons or memory["travel_style"] == "轻松":
        rec["strategy"] = "light_trip"
    elif "不喜欢" in reasons and "历史文化" in memory["preferred_types"]:
        rec["strategy"] = "scenic_first"
    elif any(w in (state["context"]["weather"] or "") for w in ["雨", "Rain"]):
        rec["strategy"] = "indoor_first"
    elif "历史文化" in memory["preferred_types"]:
        rec["strategy"] = "culture_first"
    else:
        rec["strategy"] = "scenic_first"

    rec["rejected_count"] = 0
    rec["auto_backup_notes"].append(f"已反思并切换策略为 {rec['strategy']}")
    return f"已反思失败原因，并将推荐策略调整为 {rec['strategy']}。"


def format_tool_result(result: Dict[str, Any]) -> str:
    if result.get("ok"):
        return result.get("summary") or str(result)
    return result.get("error", "未知错误")


def auto_select_available_candidate(state: Dict[str, Any]) -> str:
    rec = state["recommendation"]
    notes = []

    for item in rec["candidates"]:
        if item["name"] in rec["rejected_names"]:
            notes.append(f"跳过 {item['name']}，因为用户之前已经拒绝。")
            continue

        availability = check_ticket_availability(item["name"])
        if availability["available"]:
            rec["current"] = item
            if all(shown["name"] != item["name"] for shown in rec["shown"]):
                rec["shown"].append(item)
            if notes:
                rec["auto_backup_notes"].extend(notes)
            summary = f"系统已自动完成门票检查，当前可推荐景点为 {item['name']}。理由：{item['description']} 门票{item['price']}元。"
            if notes:
                summary = "；".join(notes + [summary])
            return summary

        notes.append(f"{item['name']}门票已售罄，已自动尝试下一个备选。")

    rec["current"] = None
    rec["auto_backup_notes"].extend(notes)
    return "；".join(notes) if notes else "当前没有可用景点，请重新规划策略。"


def handle_tool_action(tool_name: str, kwargs: Dict[str, str], state: Dict[str, Any]) -> str:
    if tool_name not in available_tools:
        return f"错误:未定义的工具 '{tool_name}'"

    result = available_tools[tool_name](**kwargs)
    if not isinstance(result, dict):
        return str(result)

    if tool_name == "get_weather" and result.get("ok"):
        state["context"]["city"] = result["city"]
        state["context"]["weather"] = result["weather"]
        state["context"]["temp_c"] = result["temp_c"]
        return result["summary"]

    if tool_name == "get_attraction_candidates" and result.get("ok"):
        filtered = [
            item for item in result["candidates"]
            if item["name"] not in state["recommendation"]["rejected_names"]
        ]
        state["recommendation"]["candidates"] = filtered
        return auto_select_available_candidate(state)

    if tool_name == "check_ticket_availability":
        if result.get("ok"):
            return f"{result['name']}：{'可用' if result['available'] else '已售罄'}，原因：{result['reason']}"
        return result.get("error", "错误: 检查票务失败")

    return format_tool_result(result)


def get_preference_hint(state: Dict[str, Any]) -> str:
    memory = state["memory"]
    preference = memory["preferred_types"][0] if memory["preferred_types"] else ""
    budget = str(memory["budget"]) if memory["budget"] is not None else ""
    return preference, budget


def parse_action(llm_output: str) -> Dict[str, str]:
    action_match = re.search(r"Action:\s*(.*)", llm_output, re.DOTALL)
    if not action_match:
        return {"type": "none", "raw": llm_output}

    action_str = action_match.group(1).strip()

    finish_match = re.match(r"Finish\[(.*)\]", action_str, re.DOTALL)
    if finish_match:
        return {"type": "finish", "answer": finish_match.group(1).strip()}

    remember_match = re.match(
        r'Remember\[\s*key="([^"]+)"\s*,\s*value="([^"]*)"\s*\]',
        action_str,
        re.DOTALL,
    )
    if remember_match:
        return {
            "type": "remember",
            "key": remember_match.group(1),
            "value": remember_match.group(2),
        }

    tool_match = re.search(r"(\w+)\((.*)\)", action_str, re.DOTALL)
    if tool_match:
        kwargs = dict(re.findall(r'(\w+)="([^"]*)"', tool_match.group(2)))
        return {
            "type": "tool",
            "name": tool_match.group(1),
            **kwargs,
        }

    return {"type": "invalid", "raw": action_str}


def format_final_answer(state: Dict[str, Any], fallback_note: str = "") -> str:
    current = state["recommendation"]["current"]
    if not current:
        return fallback_note or "抱歉，我暂时没有找到合适且可用的景点。"

    weather = state["context"].get("weather") or "当前天气"
    temp_c = state["context"].get("temp_c")
    temp_text = f"，气温{temp_c}摄氏度" if temp_c is not None else ""
    city = state["context"].get("city") or "该城市"
    notes = state["recommendation"].get("auto_backup_notes", [])
    note_text = f" 另外，{'；'.join(notes[-2:])}。" if notes else ""
    return (
        f"今天{city}天气为{weather}{temp_text}。"
        f"推荐你去{current['name']}：{current['description']}"
        f"门票{current['price']}元，类型为{current['type']}。{note_text}"
    )


def run_agent(user_prompt: str, agent_state: Optional[Dict[str, Any]] = None, max_turns: int = 6) -> str:
    state = agent_state or build_initial_state()
    prompt_history = [f"用户请求: {user_prompt}"]

    preference_updates = extract_preferences_from_text(user_prompt, state)
    rejection_note = apply_rejection_feedback(user_prompt, state)
    for note in preference_updates:
        prompt_history.append(f"Observation: {note}")
    if rejection_note:
        prompt_history.append(f"Observation: {rejection_note}")

    print(f"用户输入: {user_prompt}\n" + "=" * 40)

    for i in range(max_turns):
        print(f"--- 循环 {i + 1} ---\n")
        system_prompt = build_system_prompt(state)
        full_prompt = "\n".join(prompt_history)
        llm_output = llm.generate(full_prompt, system_prompt=system_prompt)

        if llm_output.startswith("错误:"):
            fallback = format_final_answer(state, fallback_note=llm_output)
            print(f"模型输出:\n{llm_output}\n")
            print(f"任务完成，最终答案: {fallback}")
            return fallback

        match = re.search(
            r"(Thought:.*?Action:.*?)(?=\n\s*(?:Thought:|Action:|Observation:)|\Z)",
            llm_output,
            re.DOTALL,
        )
        if match:
            llm_output = match.group(1).strip()

        print(f"模型输出:\n{llm_output}\n")
        prompt_history.append(llm_output)

        action = parse_action(llm_output)
        if action["type"] == "finish":
            final_answer = action["answer"] or format_final_answer(state)
            print(f"任务完成，最终答案: {final_answer}")
            return final_answer

        if action["type"] == "remember":
            observation = update_memory(state, action["key"], action["value"])
            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n" + "=" * 40)
            prompt_history.append(observation_str)
            continue

        if action["type"] == "tool":
            tool_name = action.pop("name")
            action.pop("type", None)
            observation = handle_tool_action(tool_name, action, state)
            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n" + "=" * 40)
            prompt_history.append(observation_str)
            continue

        if state["recommendation"]["current"]:
            final_answer = format_final_answer(state)
            print(f"任务完成，最终答案: {final_answer}")
            return final_answer

        observation_str = "Observation: 错误: 未能解析到可执行动作。"
        print(f"{observation_str}\n" + "=" * 40)
        prompt_history.append(observation_str)

    final_answer = format_final_answer(state, fallback_note="达到最大循环次数，已返回当前最优推荐。")
    print(f"任务完成，最终答案: {final_answer}")
    return final_answer


def start_chat_session() -> None:
    state = build_initial_state()
    user_prompt = input("请输入你的旅行需求：").strip()
    if not user_prompt:
        user_prompt = "你好，请帮我查询一下今天北京的天气，然后根据天气推荐一个合适的旅游景点。"

    answer = run_agent(user_prompt, state)
    print("\n助手:", answer)

    while True:
        follow_up = input("\n继续输入你的反馈（输入 exit 退出）：").strip()
        if not follow_up:
            continue
        if follow_up.lower() in {"exit", "quit", "q"}:
            print("会话结束。")
            break

        answer = run_agent(follow_up, state, max_turns=4)
        print("\n助手:", answer)


if __name__ == "__main__":
    start_chat_session()

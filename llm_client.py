import time
from openai import OpenAI


class OpenAICompatibleClient:
    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str, system_prompt: str, max_retries: int = 3) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=False,
                )

                if not response or not getattr(response, "choices", None):
                    return "错误: 模型返回为空，未提供 choices。"

                choice = response.choices[0]
                message = getattr(choice, "message", None)
                if message is None:
                    return "错误: 模型返回中 message 为空。"

                content = getattr(message, "content", None)
                reasoning = getattr(message, "reasoning_content", None)

                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )

                if content:
                    return content.strip()
                if reasoning:
                    return f"Thought: {reasoning}\nAction: Finish[已完成推理，但未返回最终正文，请重试一次。]"

                return "错误: 模型返回 message 存在，但 content 为空。"
            except Exception as e:
                err = str(e)
                if "429" in err and attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                return f"错误:调用语言模型服务时出错。{e}"

        return "错误:调用语言模型服务时出错。超过最大重试次数。"

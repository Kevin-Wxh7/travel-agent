# 智能旅行助手 Travel Agent

一个基于 **Thought-Action-Observation** 循环的 Python 智能体示例项目。  
它可以先查询指定城市的实时天气，再结合天气情况推荐合适的旅游景点。

## 功能简介

当前版本支持：

- 查询城市实时天气
- 根据天气推荐旅游景点
- 使用大语言模型进行任务分解与决策
- 通过 Thought / Action / Observation 循环逐步完成任务
- 支持 OpenAI 兼容接口的模型服务

## 项目结构

```bash
.
├── main.py              # 主循环入口，负责执行 Thought-Action-Observation
├── prompt.py            # 系统提示词
├── tools.py             # 工具函数：天气查询、景点推荐
├── llm_client.py        # OpenAI 兼容模型客户端
├── requirements.txt     # Python 依赖
└── .env                 # 环境变量（本地使用，不要上传）
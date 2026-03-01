# YukiShadow Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    5090 Desktop (Main Host)                  │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────┐  │
│  │  LLM Backend │  │  Orchestrator │  │   MCP Server    │  │
│  │  Ollama /    │  │  (FastAPI     │  │  (stdio, for    │  │
│  │  OpenAI /    │  │   :8080)      │  │  Claude Desktop)│  │
│  │  Anthropic   │  │               │  │                 │  │
│  └──────────────┘  └───────────────┘  └─────────────────┘  │
│                           │                                  │
│  ┌──────────────┐  ┌──────┴────────┐  ┌─────────────────┐  │
│  │  Scheduler   │  │  Skill        │  │   Discord Bot   │  │
│  │  (APSched)   │  │  Registry     │  │   (discord.py)  │  │
│  └──────────────┘  └───────────────┘  └─────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │   Redis (Message Bus + Task Queue)  :6379           │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌───────────────────┐  ┌──────────────────────────────┐    │
│  │  SQLite (reminders│  │  ChromaDB (vector store)     │    │
│  │  task_logs, etc.) │  │  :8001                       │    │
│  └───────────────────┘  └──────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Mosquitto MQTT Broker  :1883                      │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────────────┬──────────────────────────┘
                                   │ MQTT
                                   ▼
                    ┌──────────────────────────────┐
                    │   Jetson Orin Nano 8GB        │
                    │   - Robot control             │
                    │   - Vision models (YOLO, etc) │
                    │   - SLAM / 2D mapping         │
                    │   - jetson/mqtt_client.py     │
                    └──────────────────────────────┘
```

## Message Bus Channels

| Channel | Direction | Description |
|---|---|---|
| `events:reminder:created` | skill → scheduler | New reminder to schedule |
| `events:reminder:deleted` | skill → scheduler | Cancel a scheduled job |
| `events:reminder:fired` | scheduler → all | Reminder has triggered |
| `events:discord:send_message` | any → discord bot | Send a message/embed |
| `events:discord:message_received` | discord bot → orchestrator | User sent a message |
| `events:jetson:command` | orchestrator → mqtt bridge | Control command for Jetson |
| `events:jetson:status` | mqtt bridge → orchestrator | Jetson status update |
| `events:jetson:sensor` | mqtt bridge → orchestrator | Sensor data from Jetson |
| `queue:orchestrator` | any → orchestrator | Task queue for agent runner |

## Adding a New Skill

1. Create `skills/<name>/skill.py` with a class extending `BaseSkill`
2. Implement `metadata` property and `execute()` method
3. Add MCPToolDef entries to expose the skill via MCP
4. Register in `orchestrator/skill_registry.py` BUILTIN_SKILLS dict
5. The skill is immediately available via REST API, agent, Discord, and MCP

## LLM Provider Selection

Priority (highest wins):
1. Explicit `provider=` argument in code
2. `LLM_SKILL_OVERRIDES=skill_name=provider` in .env
3. `LLM_DEFAULT_PROVIDER` in .env (default: `ollama`)

## Deployment (Quick Start)

```bash
# 1. Install Ollama and pull a model
ollama pull qwen2.5:14b

# 2. Start infrastructure
docker compose up -d

# 3. Install Python dependencies
pip install -e .

# 4. Configure
cp .env.example .env
# Edit .env: add DISCORD_BOT_TOKEN, DISCORD_NOTIFICATION_CHANNEL_ID

# 5. Run all services
python main.py all

# 6. For MCP: orchestrator must be running, then configure Claude Desktop
# See docs/claude_desktop_mcp.json
```

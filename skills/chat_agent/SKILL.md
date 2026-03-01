---
name: chat_agent
description: Autonomous chat agent that reads and replies to messages in WeChat, Telegram, Slack, and similar platforms based on user-defined goals.
version: "0.1.0"
llm_provider: null

actions:
  set_goal:
    description: Set or update the agent's goal in a specific group or channel.
    parameters:
      platform:
        type: string
        required: true
        description: Messaging platform. Values: wechat | telegram | slack | discord_dm
      target:
        type: string
        required: true
        description: Group name, channel name, or contact identifier.
      goal:
        type: string
        required: true
        description: >
          Natural-language description of what the agent should achieve.
          E.g. "Coordinate with the team about the project deadline. Keep it
          professional. Don't commit to any dates without asking me first."
      persona:
        type: string
        description: >
          Optional persona description the agent should adopt.
          If omitted, replies neutrally on behalf of the user.

  clear_goal:
    description: Stop the agent from acting in a specific group/channel.
    parameters:
      platform:
        type: string
        required: true
      target:
        type: string
        required: true

  list_goals:
    description: List all active agent goals across all platforms.
    parameters: {}

  get_summary:
    description: Get a summary of recent activity in a group/channel.
    parameters:
      platform:
        type: string
        required: true
      target:
        type: string
        required: true
      last_n_messages:
        type: integer
        default: 50
---

# Chat Agent Skill  *(not yet implemented)*

Autonomous agent that participates in group chats on behalf of the user.
The user sets a high-level goal; the agent reads messages, decides whether to
reply, and crafts responses aligned with that goal.

## Planned use cases

- **Coordination bots**: "Help me coordinate the event planning group — focus on
  locking in a date this week. Don't agree to anything without checking with me."
- **Customer-facing assistant**: "Answer common questions in the support channel.
  Escalate anything about billing to me."
- **Information gatherer**: "Monitor the tech news Telegram group and DM me a
  daily summary of the most important items."

## When to use *(once implemented)*

- User wants to automate participation in a chat group
- User needs to monitor a channel and act on relevant messages
- User wants to delegate negotiation or coordination tasks

## Implementation notes (for developers)

- WeChat: use `itchat` or `WeChatPy` (Linux/Mac) or a virtual phone approach
- Telegram: use `python-telegram-bot` or `telethon`
- Slack: use `slack_bolt`
- Core loop: receive message → check goal → decide to reply (LLM) → post reply
- Safety guardrails: never commit to money/dates without user confirmation
- Keep a local message log per channel for context window management
- Rate-limit replies to avoid spam detection
- Notify user via Discord when a significant decision or escalation occurs

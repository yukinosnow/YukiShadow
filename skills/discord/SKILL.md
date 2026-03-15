---
name: discord
description: Interact with Discord — send messages, read channel history, and reply to users.
version: "0.2.0"
llm_provider: null

actions:
  send_message:
    description: Send a message or embed to a Discord channel.
    parameters:
      message:
        type: string
        description: >
          Plain-text content of the message.
          Can be empty string if an embed is provided instead.
      channel_id:
        type: integer
        description: >
          Target channel ID. If omitted, uses DISCORD_NOTIFICATION_CHANNEL_ID
          from the environment config.
      embed:
        type: object
        description: Optional Discord embed for rich formatting.
        properties:
          title:
            type: string
          description:
            type: string
          color:
            type: integer
            description: >
              Decimal RGB color value.
              Common values: 5814783 (blue), 5763719 (green),
              15548997 (red), 16705372 (orange).
          fields:
            type: array
            description: List of {name, value, inline} field objects.

  get_messages:
    description: >
      Fetch recent messages sent by non-bot users from a channel.
      Returns a list of {id, author_id, author_name, content, timestamp}.
    parameters:
      channel_id:
        type: integer
        description: >
          Channel to read from. If omitted, uses DISCORD_NOTIFICATION_CHANNEL_ID.
      limit:
        type: integer
        description: Maximum number of messages to return (default 10, max 100).

  reply_to_message:
    description: Reply to a specific Discord message by ID.
    parameters:
      message_id:
        type: integer
        description: ID of the message to reply to.
      channel_id:
        type: integer
        description: Channel the message belongs to.
      content:
        type: string
        description: Reply text content.
---

# Discord Skill

Interacts with Discord on behalf of the user: send notifications, read recent
messages, and reply directly to users.

## When to use

| Situation | Action |
|-----------|--------|
| Send a notification or status update | `send_message` |
| Check what users have been saying recently | `get_messages` |
| Reply to a specific user message | `reply_to_message` |

## Usage examples

| User says | Action | Key params |
|-----------|--------|------------|
| "Send me a Discord message: the build is done" | `send_message` | message="the build is done" |
| "What did people say in Discord recently?" | `get_messages` | limit=5 |
| "Reply to that message saying thanks" | `reply_to_message` | message_id=..., channel_id=..., content="thanks" |

## Embed tips

Use embeds when the content is structured or needs visual separation:
- Reminder notifications → orange embed (color: 16705372)
- Success/done → green embed (color: 5763719)
- Errors / warnings → red embed (color: 15548997)
- General info → blue embed (color: 5814783)

Plain `message` is fine for short, conversational replies.

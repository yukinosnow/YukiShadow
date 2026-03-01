---
name: discord
description: Interact with Discord — send messages, embeds, and notifications to channels.
version: "0.1.0"
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
---

# Discord Skill

Interacts with Discord on behalf of the user. Currently supports sending
messages and rich embeds to any channel the bot has access to.

## When to use

Invoke this skill when the user:
- Wants to send a custom message to Discord ("send a Discord message saying…")
- Another skill needs to notify the user (e.g. Reminder fires and calls this
  skill to deliver the notification — this happens automatically)

## Usage examples

| User says | Action | Key params |
|-----------|--------|------------|
| "Send me a Discord message: the build is done" | `send_message` | message="the build is done" |
| "Post a status update to Discord" | `send_message` | message="...", embed={...} |

## Embed tips

Use embeds when the content is structured or needs visual separation:
- Reminder notifications → orange embed (color: 16705372)
- Success/done → green embed (color: 5763719)
- Errors / warnings → red embed (color: 15548997)
- General info → blue embed (color: 5814783)

Plain `message` is fine for short, conversational replies.

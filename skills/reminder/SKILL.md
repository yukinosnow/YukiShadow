---
name: reminder
description: Create and manage time-based reminders that send Discord notifications.
version: "0.1.0"
llm_provider: null

actions:
  create_reminder:
    description: Schedule a one-time or recurring reminder.
    parameters:
      title:
        type: string
        required: true
        description: Short reminder title shown in the notification.
      scheduled_at:
        type: string
        required: true
        description: >
          ISO 8601 datetime string (e.g. "2026-03-15T15:00:00").
          Always convert natural-language times to ISO before calling.
      description:
        type: string
        description: Optional extra detail shown below the title.
      is_recurring:
        type: boolean
        default: false
        description: Set true for recurring reminders.
      recurrence_rule:
        type: string
        description: >
          Standard 5-field cron expression.
          Examples: "0 9 * * 1-5" (9am weekdays), "0 21 * * *" (9pm daily).
          Required when is_recurring is true.
      channels:
        type: array
        default: ["discord"]
        description: Notification channels. Currently only "discord" is supported.

  list_reminders:
    description: List upcoming reminders that have not fired yet.
    parameters:
      limit:
        type: integer
        default: 10
        description: Maximum number of reminders to return.

  delete_reminder:
    description: Delete (cancel) a reminder by its numeric ID.
    parameters:
      reminder_id:
        type: integer
        required: true
        description: The ID from a previous create_reminder or list_reminders call.
---

# Reminder Skill

Schedules time-based notifications. When a reminder fires, it sends a message
to the user's Discord channel (or other configured channels in the future).

## When to use

Invoke this skill when the user:
- Asks to be reminded about something at a specific time
  ("remind me to…", "set a reminder for…", "alert me at…")
- Wants to view or list their reminders
- Wants to delete or cancel a reminder

## Usage examples

| User says | Action | Key params |
|-----------|--------|------------|
| "Remind me to take medication at 9pm every day" | `create_reminder` | title="Take medication", scheduled_at=today@21:00, is_recurring=true, recurrence_rule="0 21 * * *" |
| "Set a reminder for tomorrow 3pm: team standup" | `create_reminder` | title="Team standup", scheduled_at=tomorrow@15:00 |
| "What reminders do I have?" | `list_reminders` | — |
| "Delete reminder 5" | `delete_reminder` | reminder_id=5 |
| "Cancel all my reminders" | `list_reminders` then `delete_reminder` for each | — |

## Important notes

- **`scheduled_at` must be ISO 8601.** Resolve relative phrases like "tomorrow at 3pm"
  or "in 2 hours" to a concrete datetime before calling. Use the user's timezone
  (Asia/Shanghai by default).
- **Recurring reminders** require both `is_recurring: true` and a valid `recurrence_rule`
  cron expression. Non-recurring reminders without `recurrence_rule` fire exactly once.
- After creating a reminder, confirm the exact time back to the user in a friendly
  human-readable format.
- If the user asks to "snooze" a reminder, delete the old one and create a new one.

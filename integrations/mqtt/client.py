"""
YukiShadow - MQTT Bridge (5090 side)

Bridges between the Redis message bus and MQTT, so the Jetson Orin Nano
can communicate with the orchestrator.

Topics (5090 → Jetson):   yukishadow/jetson/command
Topics (Jetson → 5090):   yukishadow/jetson/status
                           yukishadow/jetson/sensor

Run this service only when you have a Jetson connected.
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiomqtt

from core.message_bus import message_bus

logger = logging.getLogger(__name__)

TOPIC_COMMAND = "yukishadow/jetson/command"
TOPIC_STATUS = "yukishadow/jetson/status"
TOPIC_SENSOR = "yukishadow/jetson/sensor"
TOPIC_VISION = "yukishadow/jetson/vision"


async def run_mqtt_bridge() -> None:
    """Bridge between MQTT (Jetson) and Redis message bus (orchestrator)."""
    from core.config import settings
    await message_bus.connect()

    async with aiomqtt.Client(hostname=settings.mqtt_host, port=settings.mqtt_port) as mqtt:
        await mqtt.subscribe(TOPIC_STATUS)
        await mqtt.subscribe(TOPIC_SENSOR)
        await mqtt.subscribe(TOPIC_VISION)
        logger.info(f"MQTT bridge connected to {settings.mqtt_host}:{settings.mqtt_port}")

        # Forward Redis commands to Jetson in background
        relay_task = asyncio.create_task(_relay_commands_to_jetson(mqtt))

        try:
            async for message in mqtt.messages:
                payload = _safe_parse(message.payload)
                topic = str(message.topic)

                if TOPIC_STATUS in topic:
                    await message_bus.publish("events:jetson:status", payload)
                elif TOPIC_SENSOR in topic:
                    await message_bus.publish("events:jetson:sensor", payload)
                elif TOPIC_VISION in topic:
                    await message_bus.publish("events:jetson:vision", payload)
        finally:
            relay_task.cancel()
            await message_bus.disconnect()


async def _relay_commands_to_jetson(mqtt: aiomqtt.Client) -> None:
    """Listen for orchestrator commands on the bus and publish to Jetson via MQTT."""
    async for event in message_bus.subscribe("events:jetson:command"):
        try:
            await mqtt.publish(TOPIC_COMMAND, json.dumps(event))
        except Exception as e:
            logger.error(f"Failed to relay command to Jetson: {e}")


def _safe_parse(payload: bytes | str) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(payload)}

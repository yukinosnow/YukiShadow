"""
YukiShadow - Jetson MQTT Client

Runs ON the Jetson Orin Nano (not the 5090).
Connects to the MQTT broker on the 5090 machine, receives commands,
and sends back status/sensor data.

Deploy:
  1. Copy the jetson/ directory to the Jetson
  2. pip install aiomqtt
  3. Set ORCHESTRATOR_HOST to the 5090's IP address
  4. python -m jetson.mqtt_client
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aiomqtt

logger = logging.getLogger(__name__)

# ── Configuration (override via env vars on the Jetson) ───────────────────────
ORCHESTRATOR_HOST = os.getenv("ORCHESTRATOR_HOST", "192.168.1.100")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
STATUS_INTERVAL = int(os.getenv("STATUS_INTERVAL_SEC", "30"))

TOPIC_COMMAND = "yukishadow/jetson/command"
TOPIC_STATUS = "yukishadow/jetson/status"
TOPIC_SENSOR = "yukishadow/jetson/sensor"
TOPIC_VISION = "yukishadow/jetson/vision"


class JetsonAgent:
    """Handles robot control and sensor reporting on the Jetson."""

    def __init__(self) -> None:
        # Replace with actual robot controller when hardware is ready
        self._robot = None  # e.g. from robot_controller import RobotController

    async def handle_command(self, client: aiomqtt.Client, command: dict) -> None:
        cmd_type = command.get("type", "")
        logger.info(f"Command received: {cmd_type} | {command}")

        if cmd_type == "move":
            await self._move(command)
        elif cmd_type == "stop":
            await self._stop()
        elif cmd_type == "get_status":
            await self._publish_status(client)
        elif cmd_type == "run_vision":
            # Trigger a vision inference task
            result = await self._run_vision(command.get("model", "yolo"))
            await client.publish(TOPIC_VISION, json.dumps(result))
        else:
            logger.warning(f"Unknown command type: {cmd_type}")

    async def _move(self, command: dict) -> None:
        direction = command.get("direction", "stop")
        speed = float(command.get("speed", 0.5))
        logger.info(f"Move: direction={direction}, speed={speed}")
        if self._robot:
            pass  # self._robot.move(direction, speed)

    async def _stop(self) -> None:
        logger.info("Stop command received")
        if self._robot:
            pass  # self._robot.stop()

    async def _run_vision(self, model: str) -> dict:
        logger.info(f"Running vision model: {model}")
        # Placeholder: return dummy result
        return {"model": model, "detections": [], "status": "stub"}

    async def _publish_status(self, client: aiomqtt.Client) -> None:
        status = {
            "type": "status",
            "host": ORCHESTRATOR_HOST,
            "robot_connected": self._robot is not None,
            "uptime_ok": True,
        }
        await client.publish(TOPIC_STATUS, json.dumps(status))
        logger.debug("Status published")


async def run() -> None:
    agent = JetsonAgent()
    logger.info(f"Connecting to MQTT broker at {ORCHESTRATOR_HOST}:{MQTT_PORT}")

    async with aiomqtt.Client(hostname=ORCHESTRATOR_HOST, port=MQTT_PORT) as client:
        await client.subscribe(TOPIC_COMMAND)
        logger.info("Jetson agent ready, waiting for commands...")

        # Periodic status reports
        asyncio.create_task(_status_loop(client, agent))

        async for message in client.messages:
            try:
                command = json.loads(message.payload)
                await agent.handle_command(client, command)
            except Exception:
                logger.exception("Error handling command")


async def _status_loop(client: aiomqtt.Client, agent: JetsonAgent) -> None:
    while True:
        await asyncio.sleep(STATUS_INTERVAL)
        await agent._publish_status(client)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

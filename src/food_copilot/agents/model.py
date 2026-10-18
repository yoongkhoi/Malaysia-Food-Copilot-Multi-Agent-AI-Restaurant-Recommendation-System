"""OpenAI calls stay on the server. Status checks never return the key."""

import json
import logging
import os

from food_copilot.config.settings import temperature_for
from food_copilot.errors import ModelCallError, ModelConfigError
from food_copilot.memory.store import load_local_env

logger = logging.getLogger("food_copilot.model")


def _create(client, kwargs: dict):
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        if "temperature" not in kwargs or "temperature" not in str(exc).lower():
            raise
        logger.warning("model rejected temperature; retrying without it")
        kwargs.pop("temperature", None)
        return client.chat.completions.create(**kwargs)


def openai_status() -> dict:
    load_local_env()
    return {
        "configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
    }


class OpenAIChatModel:
    """One chat completion. Tool calls are returned for the agent to execute."""

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        timeout: float = 8,
        max_tokens: int = 180,
        temperature: float | None = None,
        role: str | None = None,
    ) -> dict:
        load_local_env()
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ModelConfigError("OPENAI_API_KEY is not set")
        model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
        chosen = temperature_for(role or "general") if temperature is None else temperature
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelConfigError("The OpenAI SDK is not installed.") from exc
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        kwargs = {
            "model": model_name,
            "messages": messages,
            "tools": tools or None,
            "temperature": chosen,
            "max_tokens": max_tokens,
        }
        started_role = role or "general"
        try:
            response = _create(client, kwargs)
        except Exception as exc:
            text = str(exc).lower()
            if "timeout" in text or exc.__class__.__name__.lower().find("timeout") >= 0:
                raise ModelCallError("The model request timed out.") from exc
            raise ModelCallError("The model request failed.") from exc
        logger.info("agent=%s model=%s temperature=%s", started_role, model_name, kwargs.get("temperature"))
        message = response.choices[0].message
        tool_calls = []
        for call in message.tool_calls or []:
            raw = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
        return {"content": message.content or "", "tool_calls": tool_calls}

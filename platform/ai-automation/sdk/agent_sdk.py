"""Agent SDK – tools for building custom agents and plugins."""
from __future__ import annotations

import abc
import json
import re
from typing import Any, Callable, Dict, List, Optional


class PromptTemplate:
    """Simple Jinja2-style template for prompt construction."""

    def __init__(self, template: str):
        self._template = template

    def render(self, **kwargs) -> str:
        def replace(m):
            key = m.group(1).strip()
            return str(kwargs.get(key, m.group(0)))
        return re.sub(r"\{\{(.+?)\}\}", replace, self._template)


class AgentMemory:
    """In-memory key-value store with optional persistence."""

    def __init__(self):
        self._store: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def to_dict(self) -> Dict:
        return dict(self._store)

    def load(self, data: Dict) -> None:
        self._store.update(data)


class AgentPlugin(abc.ABC):
    """Base class for agent plugins that extend agent capabilities."""

    name: str = "plugin"
    description: str = ""

    @abc.abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        pass


class AgentBuilder:
    """Fluent builder for configuring custom agents."""

    def __init__(self, name: str):
        self._name = name
        self._system_prompt: Optional[str] = None
        self._provider: Optional[str] = None
        self._model: Optional[str] = None
        self._max_tokens: int = 1024
        self._temperature: float = 0.7
        self._plugins: List[AgentPlugin] = []
        self._memory = AgentMemory()
        self._tools: List[Callable] = []

    def system_prompt(self, prompt: str) -> "AgentBuilder":
        self._system_prompt = prompt
        return self

    def provider(self, name: str, model: Optional[str] = None) -> "AgentBuilder":
        self._provider = name
        self._model = model
        return self

    def temperature(self, temp: float) -> "AgentBuilder":
        self._temperature = max(0.0, min(2.0, temp))
        return self

    def max_tokens(self, n: int) -> "AgentBuilder":
        self._max_tokens = n
        return self

    def add_plugin(self, plugin: AgentPlugin) -> "AgentBuilder":
        self._plugins.append(plugin)
        return self

    def remember(self, key: str, value: Any) -> "AgentBuilder":
        self._memory.set(key, value)
        return self

    def build(self) -> "BuiltAgent":
        return BuiltAgent(
            name=self._name,
            system_prompt=self._system_prompt,
            provider=self._provider,
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            plugins=self._plugins,
            memory=self._memory,
        )


class BuiltAgent:
    """A configured agent ready for execution."""

    def __init__(self, name: str, system_prompt: Optional[str] = None,
                 provider: Optional[str] = None, model: Optional[str] = None,
                 max_tokens: int = 1024, temperature: float = 0.7,
                 plugins: Optional[List[AgentPlugin]] = None,
                 memory: Optional[AgentMemory] = None):
        self.name = name
        self.system_prompt = system_prompt
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.plugins = plugins or []
        self.memory = memory or AgentMemory()

    async def run(self, prompt: str, context: Optional[Dict] = None) -> str:
        from ..ai.provider import get_registry
        registry = get_registry()
        ai_provider = registry.get(self.provider)

        full_context = self.memory.to_dict()
        if context:
            full_context.update(context)

        # Run any pre-plugins
        plugin_outputs = {}
        for plugin in self.plugins:
            try:
                out = await plugin.execute(full_context)
                plugin_outputs[plugin.name] = out
            except Exception:
                pass

        enhanced_prompt = prompt
        if plugin_outputs:
            enhanced_prompt += "\n\nContext:\n" + json.dumps(plugin_outputs, indent=2)

        result = await ai_provider.complete(
            prompt=enhanced_prompt,
            system_prompt=self.system_prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return result.get("content", "")

"""A coding agent that talks to ANY OpenAI-compatible local model server —
LM Studio, llama.cpp's server, vLLM, or even Ollama's own /v1 endpoint.

This decouples the platform from any single backend: point base_url at whichever
local-AI app is running and the same evaluation pipeline just works. All the
file-reading, prompting, and code-block parsing is inherited from OllamaAgent;
only the network call differs (POST /v1/chat/completions instead of Ollama's
native /api/generate). Transport failures are classified as INFRA_FAILURE
(voided) exactly as in OllamaAgent (framework §1).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .agents_ollama import OllamaAgent


def openai_chat_generate(
    prompt: str,
    seed: int,
    *,
    model: str,
    base_url: str,
    temperature: float,
    timeout: float,
) -> str:
    """Call an OpenAI-compatible /v1/chat/completions endpoint and return the
    assistant message text. Stdlib urllib (offline-capable). Raises the same
    transport errors OllamaAgent classifies as INFRA_FAILURE."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "seed": seed,          # honored by LM Studio / llama.cpp; ignored elsewhere
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    url = base_url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


@dataclass
class OpenAICompatAgent(OllamaAgent):
    """OllamaAgent that speaks the OpenAI chat API instead of Ollama's native
    one. Defaults to LM Studio's local server (port 1234). Set `model` to the
    served model id (e.g. "mistralai/ministral-3-14b-reasoning").

    Example:
        OpenAICompatAgent(name="lmstudio", model="mistralai/ministral-3-14b-reasoning")
        OpenAICompatAgent(name="ollama-v1", model="qwen2.5-coder:7b",
                          base_url="http://localhost:11434")  # Ollama's /v1
    """

    base_url: str = "http://localhost:1234"   # LM Studio default

    def _default_generate(self, prompt: str, seed: int) -> str:
        return openai_chat_generate(
            prompt,
            seed,
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            timeout=self.request_timeout,
        )

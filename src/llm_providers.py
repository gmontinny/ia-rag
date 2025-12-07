from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    temperature: float = 0.2
    max_tokens: int = 800


class LLMProvider:
    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 800) -> str:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        import google.generativeai as genai  # type: ignore

        self._genai = genai
        genai.configure(api_key=api_key)
        self.model_name = model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 800) -> str:
        # Gemini v1/v3 aceita system instruction no modelo
        model = self._genai.GenerativeModel(model_name=self.model_name, system_instruction=system_prompt)
        resp = model.generate_content(user_prompt, generation_config={
            "temperature": float(temperature),
            "max_output_tokens": int(max_tokens),
        })
        # Some SDK versions expose .text; else join candidates
        try:
            if hasattr(resp, "text") and resp.text:
                return resp.text
        except Exception:
            pass
        try:
            parts = []
            for c in getattr(resp, "candidates", []) or []:
                for p in getattr(c, "content", {}).get("parts", []) or []:
                    parts.append(str(getattr(p, "text", "")))
            return "\n".join([p for p in parts if p]).strip()
        except Exception:
            return ""


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        from openai import OpenAI  # type: ignore

        self.client = OpenAI(api_key=api_key)
        self.model = model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 800) -> str:
        # Usa Chat Completions para compatibilidade ampla
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()


def make_provider(provider: str, model: str, api_key: str) -> LLMProvider:
    p = (provider or "").lower().strip()
    if p in ("gemini", "google", "googleai"):
        return GeminiProvider(model=model, api_key=api_key)
    # default: OpenAI-like
    return OpenAIProvider(model=model, api_key=api_key)

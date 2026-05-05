"""AI provider registry — single source of truth for supported LLM presets.

Each provider declares:
- label: human-readable name for UI dropdowns
- base_url: OpenAI-compatible chat/completions endpoint
- key_field: attribute name on Settings where the API key lives
- models: list of available models, each with id, label, vision flag
"""

AI_PROVIDERS: dict[str, dict] = {
    "google": {
        "label": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_field": "google_api_key",
        "models": [
            {
                "id": "gemini-3.1-flash-lite-preview",
                "label": "Gemini 3.1 Flash Lite Preview",
                "vision": True,
            },
            {
                "id": "gemini-3-flash-preview",
                "label": "Gemini 3 Flash Preview",
                "vision": True,
            },
            {
                "id": "gemini-3.1-flash-preview",
                "label": "Gemini 3.1 Flash Preview",
                "vision": True,
            },
            {"id": "gemma-4-31b-it", "label": "Gemma 4 31B", "vision": True},
            {"id": "gemma-4-26b-a4b-it", "label": "Gemma 4 26B", "vision": True},
        ],
    },
    "nvidia": {
        "label": "NVIDIA Build",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_field": "nvidia_api_key",
        "models": [
            {"id": "moonshotai/kimi-k2.6", "label": "Kimi K2.6", "vision": True},
            {"id": "z-ai/glm-5.1", "label": "GLM 5.1", "vision": True},
            {"id": "google/gemma-4-31b-it", "label": "Gemma 4 31B", "vision": True},
            {"id": "minimaxai/minimax-m2.7", "label": "MiniMax M2.7", "vision": True},
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_field": "openrouter_api_key",
        "models": [
            {
                "id": "nvidia/nemotron-3-super-120b-a12b:free",
                "label": "Nemotron 3 Super 120B (free)",
                "vision": False,
            },
            {
                "id": "minimax/minimax-m2.5:free",
                "label": "MiniMax M2.5 (free)",
                "vision": True,
            },
            {
                "id": "google/gemma-4-31b-it:free",
                "label": "Gemma 4 31B (free)",
                "vision": True,
            },
            {
                "id": "google/gemma-4-26b-a4b-it:free",
                "label": "Gemma 4 26B (free)",
                "vision": True,
            },
        ],
    },
    "groq": {
        "label": "Groq Cloud",
        "base_url": "https://api.groq.com/openai/v1",
        "key_field": "stt_api_key",
        "models": [
            {
                "id": "llama-3.3-70b-versatile",
                "label": "Llama 3.3 70B",
                "vision": False,
            },
        ],
    },
}

# UI helpers — used by templates/controllers for conditional rendering
TEXT_PROVIDERS: dict[str, dict] = {
    k: v
    for k, v in AI_PROVIDERS.items()
    if not any(m.get("vision") for m in v["models"])
}
VISION_PROVIDERS: dict[str, dict] = {
    k: v for k, v in AI_PROVIDERS.items() if any(m.get("vision") for m in v["models"])
}

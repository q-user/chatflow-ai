"""AI provider registry — single source of truth for supported LLM presets.

Each preset declares:
- base_url: OpenAI-compatible chat/completions endpoint
- model: exact model string for the provider
- key_env: attribute name on Settings where the API key lives
- vision: whether the model supports image input
- label: human-readable name for UI dropdowns
"""

SUPPORTED_AI_PROVIDERS: dict[str, dict] = {
    "google_gemini_flash": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3-flash-preview",
        "key_env": "google_api_key",
        "vision": True,
        "label": "Gemini 1.5 Flash (Vision+Text)",
    },
}

# UI helpers — used by templates/controllers for conditional rendering
TEXT_PROVIDERS: dict[str, dict] = {
    k: v for k, v in SUPPORTED_AI_PROVIDERS.items() if not v.get("vision")
}
VISION_PROVIDERS: dict[str, dict] = {
    k: v for k, v in SUPPORTED_AI_PROVIDERS.items() if v.get("vision")
}

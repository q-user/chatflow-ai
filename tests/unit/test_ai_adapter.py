"""Unit tests for OpenRouterAdapter."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.interfaces.ai import AIServiceError
from infrastructure.ai.adapter import (
    COT_TOKEN,
    OpenRouterAdapter,
)


@pytest.fixture
def adapter() -> OpenRouterAdapter:
    """Create OpenRouterAdapter with test config."""
    return OpenRouterAdapter(
        api_key="test_api_key",
        base_url="https://openrouter.ai/api/v1",
        model="google/gemma-4-26b-a4b-it",
    )


# ──────────────────────────────────────────────
# Message construction tests
# ──────────────────────────────────────────────


def test_build_messages_text_only(adapter: OpenRouterAdapter):
    """Text-only request → simple content string."""
    messages = adapter._build_messages("system", "hello", None)
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": f"{COT_TOKEN}system"}
    assert messages[1] == {"role": "user", "content": "hello"}


def test_build_messages_empty_system_prompt(adapter: OpenRouterAdapter):
    """Empty system prompt → still prefixed with COT_TOKEN."""
    messages = adapter._build_messages("", "hello", None)
    assert messages[0]["content"] == COT_TOKEN


def test_build_messages_multimodal_images_first(
    adapter: OpenRouterAdapter, tmp_path: Path
):
    """Multimodal request → images precede text in content array."""
    # Create a fake image
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG fake image data")

    messages = adapter._build_messages("system", "describe this", [str(img_path)])
    assert len(messages) == 2
    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    assert len(user_content) == 2
    # Image MUST come first for Gemma 4
    assert user_content[0]["type"] == "image_url"
    assert user_content[1]["type"] == "text"
    assert user_content[1]["text"] == "describe this"


def test_build_messages_empty_image_paths(adapter: OpenRouterAdapter):
    """Empty image_paths list → text-only request."""
    messages = adapter._build_messages("system", "hello", [])
    assert len(messages) == 2
    assert messages[1]["content"] == "hello"  # string, not list


# ──────────────────────────────────────────────
# Image encoding tests
# ──────────────────────────────────────────────


def test_encode_image(tmp_path: Path):
    """encode_image reads file and returns base64."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake image bytes")
    result = OpenRouterAdapter._encode_image(str(img_path))
    expected = base64.b64encode(b"fake image bytes").decode("utf-8")
    assert result == expected


def test_encode_image_not_found():
    """encode_image raises AIServiceError for missing file."""
    with pytest.raises(AIServiceError, match="not found"):
        OpenRouterAdapter._encode_image("/nonexistent/path.png")


def test_guess_mime():
    """MIME type correctly guessed from extension."""
    assert OpenRouterAdapter._guess_mime("photo.jpg") == "image/jpeg"
    assert OpenRouterAdapter._guess_mime("photo.jpeg") == "image/jpeg"
    assert OpenRouterAdapter._guess_mime("image.png") == "image/png"
    assert OpenRouterAdapter._guess_mime("anim.gif") == "image/gif"
    assert OpenRouterAdapter._guess_mime("pic.webp") == "image/webp"
    assert OpenRouterAdapter._guess_mime("doc.pdf") == "application/pdf"
    assert OpenRouterAdapter._guess_mime("data.bin") == "application/octet-stream"


# ──────────────────────────────────────────────
# Response parsing tests
# ──────────────────────────────────────────────


def test_extract_content_valid():
    """Valid response structure → content extracted."""
    response = {"choices": [{"message": {"content": "answer text"}}]}
    result = OpenRouterAdapter._extract_content(response)
    assert result == "answer text"


def test_extract_content_empty_choices():
    """Empty choices list → AIServiceError."""
    response = {"choices": []}
    with pytest.raises(AIServiceError, match="Unexpected API response"):
        OpenRouterAdapter._extract_content(response)


def test_strip_thinking_with_cot():
    """Content with CoT thinking → thinking block removed."""
    content = " reasoning here</|think|> answer"
    result = OpenRouterAdapter._strip_thinking(content)
    assert result == "answer"


def test_strip_thinking_without_cot():
    """Content without CoT → returned as-is."""
    content = "plain answer"
    result = OpenRouterAdapter._strip_thinking(content)
    assert result == "plain answer"


def test_strip_thinking_empty_after():
    """Unclosed think tag → empty string."""
    content = "<|think|>\n reasoning"
    result = OpenRouterAdapter._strip_thinking(content)
    assert result == ""


def test_strip_thinking_unclosed():
    """Unclosed think tag with no closing tag → strips from tag to end."""
    content = "<|think|>\n reasoning here\n# Header"
    result = OpenRouterAdapter._strip_thinking(content)
    assert result == ""


def test_strip_thinking_edge_cases():
    """Various edge cases for strip_thinking."""
    # 1. Think end tag at the start
    assert OpenRouterAdapter._strip_thinking("</|think|> Answer") == "Answer"

    # 2. Empty content
    assert OpenRouterAdapter._strip_thinking("") == ""

    # 3. Content that starts with think_start_tag but has no content after
    assert OpenRouterAdapter._strip_thinking("<|think|>") == ""

    # 4. Thinking tag in the middle with no closing tag → strip from tag to end
    assert OpenRouterAdapter._strip_thinking("Hello <|think|> world") == "Hello"

    # 5. Multiple closing tags
    assert (
        OpenRouterAdapter._strip_thinking("r1</|think|> a1 </|think|> a2")
        == "a1 </|think|> a2"
    )


# ──────────────────────────────────────────────
# generate_json tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_json_valid(adapter: OpenRouterAdapter):
    """Valid JSON response → parsed dict returned."""
    mock_response = {"choices": [{"message": {"content": '{"key": "value"}'}}]}

    with patch.object(adapter, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await adapter.generate_json("system", "text")

    assert result == {"key": "value"}
    mock_call.assert_called_once()
    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["json_mode"] is True


@pytest.mark.asyncio
async def test_generate_json_with_cot_stripped(adapter: OpenRouterAdapter):
    """CoT thinking block stripped before JSON parsing."""
    mock_response = {
        "choices": [{"message": {"content": ' reasoning</|think|> {"key": "value"}'}}]
    }

    with patch.object(adapter, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await adapter.generate_json("system", "text")

    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_generate_json_strips_whitespace_after_thinking(
    adapter: OpenRouterAdapter,
):
    """Whitespace after thinking block is stripped before JSON parse."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '<|think|>reasoning</|think|>  \n\n {"key": "value"} \n'
                }
            }
        ]
    }

    with patch.object(adapter, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await adapter.generate_json("system", "text")

        assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_generate_json_raises_on_invalid_json(adapter: OpenRouterAdapter):
    """Non-JSON response → AIServiceError."""
    mock_response = {"choices": [{"message": {"content": "not valid json {{{"}}]}

    with patch.object(adapter, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        with pytest.raises(AIServiceError, match="invalid JSON"):
            await adapter.generate_json("system", "text")


# ──────────────────────────────────────────────
# generate_text tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_text_valid(adapter: OpenRouterAdapter):
    """Valid text response → text returned."""
    mock_response = {"choices": [{"message": {"content": "Hello, world!"}}]}

    with patch.object(adapter, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await adapter.generate_text("system", "greet")

    assert result == "Hello, world!"
    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["json_mode"] is False


# ──────────────────────────────────────────────
# _call_api tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "side_effect,match",
    [
        (httpx.TimeoutException("timeout"), "timeout"),
        (
            httpx.HTTPStatusError(
                "Rate limited", request=MagicMock(), response=MagicMock(status_code=429)
            ),
            "429",
        ),
    ],
)
async def test_call_api_exceptions(adapter: OpenRouterAdapter, side_effect, match):
    """Timeout/HTTP error → AIServiceError."""
    mock_client = AsyncMock()
    mock_client.post.side_effect = side_effect
    adapter._http = mock_client
    adapter._owns_client = False

    with pytest.raises(AIServiceError, match=match):
        await adapter._call_api([{"role": "user", "content": "hi"}])


# ──────────────────────────────────────────────
# Factory test
# ──────────────────────────────────────────────


def test_create_ai_adapter(monkeypatch):
    """create_ai_adapter returns OpenRouterAdapter with settings."""
    from infrastructure.ai import create_ai_adapter

    monkeypatch.setattr("infrastructure.config.settings.ai_api_key", "test_key")
    monkeypatch.setattr(
        "infrastructure.config.settings.ai_base_url", "https://test.api"
    )
    monkeypatch.setattr("infrastructure.config.settings.ai_model_name", "test_model")

    adapter = create_ai_adapter()
    assert isinstance(adapter, OpenRouterAdapter)
    assert adapter._api_key == "test_key"
    assert adapter._base_url == "https://test.api"
    assert adapter._model == "test_model"

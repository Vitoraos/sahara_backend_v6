import pytest

from app.config import Settings
from app.dialogue.translation import NllbTranslationProvider, TranslationProviderError


class Response:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.request = None

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


@pytest.mark.asyncio
async def test_translation_extracts_hf_style_response(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Response([{"translation_text": "hello"}])

    monkeypatch.setattr("app.dialogue.translation.httpx.AsyncClient", Client)
    provider = NllbTranslationProvider(Settings(translation_api_url="https://translator.test"))
    assert await provider.to_english("bonjour") == "hello"


@pytest.mark.asyncio
async def test_translation_requires_endpoint():
    with pytest.raises(TranslationProviderError):
        await NllbTranslationProvider(Settings()).to_english("hello")

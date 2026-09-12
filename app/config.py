from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.dialogue.danger_signs import DANGER_SIGN_PHRASES, REQUIRED_TRIAGE_FIELDS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Sahara Triage Voice Agent API'
    environment: str = 'development'
    api_prefix: str = '/api'

    supabase_url: str = Field(default='', description='Supabase project URL')
    supabase_anon_key: str = Field(default='', description='Supabase anon/public key')
    supabase_service_role_key: str = Field(default='', description='Server-only Supabase service role key')

    redis_url: str = ''
    cors_allowed_origins: str = ''

    intron_api_key: str = ''
    intron_stt_endpoint: str = 'wss://infer.voice.intron.io/stt/v1/stream'
    intron_stt_language: str = 'en'
    intron_stt_sample_rate: int = 16000
    intron_stt_bit_rate: int = 16
    intron_stt_channels: int = 1
    sahara_api_key: str = ''
    openrouter_api_key: str = ''
    openrouter_api_url: str = 'https://openrouter.ai/api/v1/chat/completions'
    openrouter_extraction_model: str = 'meta-llama/llama-3.3-70b-instruct'
    openrouter_response_model: str = 'meta-llama/llama-3.3-70b-instruct'
    openrouter_summary_model: str = 'meta-llama/llama-3.3-70b-instruct'
    africas_talking_username: str = ''
    africas_talking_api_key: str = ''
    intron_tts_endpoint: str = 'wss://infer.voice.intron.io/tts/v1/stream'
    intron_tts_voice: str = ''
    intron_tts_voice_accent: str = ''
    intron_tts_voice_gender: str = ''
    intron_tts_language: str = 'en'
    intron_tts_output_audio_format: str = 'wav'
    intron_tts_sample_rate: int = 48000
    intron_tts_text_chunk_chars: int = 100
    required_triage_fields: str = ','.join(REQUIRED_TRIAGE_FIELDS)
    danger_sign_phrases: str = ','.join(DANGER_SIGN_PHRASES)
    persistence_timeout_seconds: float = 5.0
    base_url: str = ''
    africas_talking_voice_number: str = ''
    africas_talking_webhook_secret: str = ''
    phone_record_max_seconds: int = 60
    escalation_phone_number: str = ''
    allow_dev_unauthenticated: bool = False

    external_timeout_seconds: float = 10.0
    external_max_retries: int = 2


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

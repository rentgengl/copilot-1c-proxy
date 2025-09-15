#import asyncio
import json
import logging
import os
from typing import Optional, Dict
from datetime import datetime, timedelta

import httpx
from models import (
    ConversationRequest,
    ConversationResponse,
    MessageRequest,
    MessageChunk,
    ConversationSession,
    ApiError
)

logger = logging.getLogger(__name__)


class OneCApiClient:
    """Клиент для работы с API 1С.ai через переменные окружения."""

    def __init__(self):
        self.base_url = os.getenv("ONEC_AI_BASE_URL", "https://code.1c.ai").rstrip('/')
        self.token = os.getenv("ONEC_AI_TOKEN")
        if not self.token:
            raise ValueError("Не задана переменная окружения ONEC_AI_TOKEN")

        self.timeout = int(os.getenv("ONEC_AI_TIMEOUT", "30"))
        self.ui_language = os.getenv("ONEC_AI_UI_LANGUAGE", "russian")
        self.programming_language = os.getenv("ONEC_AI_PROGRAMMING_LANGUAGE", "")
        self.script_language = os.getenv("ONEC_AI_SCRIPT_LANGUAGE", "")
        self.max_active_sessions = int(os.getenv("MAX_ACTIVE_SESSIONS", "10"))
        self.session_ttl = int(os.getenv("SESSION_TTL", "3600"))

        self.sessions: Dict[str, ConversationSession] = {}
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Accept": "*/*",
                "Accept-Charset": "utf-8",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "ru-ru,en-us;q=0.8,en;q=0.7",
                "Authorization": self.token,
                "Content-Type": "application/json; charset=utf-8",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/chat/",
                "User-Agent": "Mozilla/5.0"
            }
        )

    async def create_conversation(
        self,
        programming_language: Optional[str] = None,
        script_language: Optional[str] = None
    ) -> str:
        try:
            request_data = ConversationRequest(
                ui_language=self.ui_language,
                programming_language=programming_language or self.programming_language,
                script_language=script_language or self.script_language
            )

            response = await self.client.post(
                f"{self.base_url}/chat_api/v1/conversations/",
                json=request_data.dict(),
                headers={"Session-Id": ""}
            )

            if response.status_code != 200:
                raise ApiError(
                    f"Ошибка создания дискуссии: {response.status_code}",
                    response.status_code
                )

            conversation_response = ConversationResponse(**response.json())
            conversation_id = conversation_response.uuid
            self.sessions[conversation_id] = ConversationSession(conversation_id=conversation_id)
            logger.info(f"Создана новая дискуссия: {conversation_id}")
            return conversation_id

        except httpx.RequestError as e:
            raise ApiError(f"Ошибка сети при создании дискуссии: {str(e)}")
        except Exception as e:
            raise ApiError(f"Неожиданная ошибка при создании дискуссии: {str(e)}")

    async def send_message(self, conversation_id: str, message: str) -> str:
        try:
            if conversation_id not in self.sessions:
                self.sessions[conversation_id] = ConversationSession(conversation_id=conversation_id)

            self.sessions[conversation_id].update_usage()
            request_data = MessageRequest(instruction=message)
            url = f"{self.base_url}/chat_api/v1/conversations/{conversation_id}/messages"

            async with self.client.stream(
                "POST",
                url,
                json=request_data.dict(),
                headers={"Accept": "text/event-stream"}
            ) as response:

                if response.status_code != 200:
                    raise ApiError(
                        f"Ошибка отправки сообщения: {response.status_code}",
                        response.status_code
                    )

                full_response = await self._parse_sse_response(response)
                logger.info(f"Получен ответ для дискуссии {conversation_id}")
                return full_response

        except httpx.RequestError as e:
            raise ApiError(f"Ошибка сети при отправке сообщения: {str(e)}")
        except Exception as e:
            raise ApiError(f"Неожиданная ошибка при отправке сообщения: {str(e)}")

    async def _parse_sse_response(self, response: httpx.Response) -> str:
        full_text = ""
        response.encoding = 'utf-8'

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                try:
                    data_str = line[6:]
                    data = json.loads(data_str)
                    chunk = MessageChunk(**data)

                    if chunk.role == "assistant" and chunk.content and "text" in chunk.content:
                        text = chunk.content["text"]
                        if text:
                            text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
                            full_text = text
                        if chunk.finished:
                            break
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.warning(f"Ошибка парсинга SSE chunk: {e}")
                    continue
        return full_text.strip()

    async def get_or_create_session(
        self,
        create_new: bool = False,
        programming_language: Optional[str] = None
    ) -> str:
        await self._cleanup_old_sessions()

        if create_new or not self.sessions:
            return await self.create_conversation(programming_language)

        if len(self.sessions) >= self.max_active_sessions:
            oldest_session_id = min(self.sessions.keys(), key=lambda k: self.sessions[k].last_used)
            del self.sessions[oldest_session_id]
            logger.info(f"Удалена старая сессия: {oldest_session_id}")

        return max(self.sessions.keys(), key=lambda k: self.sessions[k].last_used)

    async def _cleanup_old_sessions(self):
        current_time = datetime.now()
        ttl_delta = timedelta(seconds=self.session_ttl)
        expired_sessions = [
            sid for sid, session in self.sessions.items()
            if current_time - session.last_used > ttl_delta
        ]
        for sid in expired_sessions:
            del self.sessions[sid]
            logger.info(f"Удалена устаревшая сессия: {sid}")

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

import logging
import os
from typing import Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from api_client import OneCApiClient

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AskAIRequest(BaseModel):
    question: str
    programming_language: Optional[str] = ""
    create_new_session: bool = False


class ExplainSyntaxRequest(BaseModel):
    syntax_element: str
    context: Optional[str] = ""


class CheckCodeRequest(BaseModel):
    code: str
    check_type: Optional[str] = "syntax"


class ResponseModel(BaseModel):
    result: str
    error: Optional[str] = None


class OneCRestServer:
    """REST-сервер для вызова методов 1С.ai без MCP."""

    def __init__(self):
        self.api_client: Optional[OneCApiClient] = None

    def _sanitize_text(self, text: str) -> str:
        """Очистка текста от проблемных Unicode-символов."""
        if not text:
            return text
        import unicodedata
        text = unicodedata.normalize('NFKC', text)
        cleaned = ''.join(
            char for char in text
            if unicodedata.category(char) not in ['Cc', 'Cf'] or char in ['\n', '\r', '\t']
        )
        return cleaned

    async def _initialize_client(self):
        """Инициализация API-клиента при первом запросе."""
        if self.api_client is None:
            try:
                self.api_client = OneCApiClient()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Ошибка подключения к API: {str(e)}")

    async def ask_1c_ai(self, request: AskAIRequest) -> ResponseModel:
        await self._initialize_client()

        if not request.question.strip():
            return ResponseModel(result="", error="Вопрос не может быть пустым")

        conversation_id = await self.api_client.get_or_create_session(
            create_new=request.create_new_session,
            programming_language=request.programming_language or None
        )

        answer = await self.api_client.send_message(conversation_id, request.question)
        clean_answer = self._sanitize_text(answer)

        return ResponseModel(result=f"Ответ от 1С.ai:\n\n{clean_answer}\n\nСессия: {conversation_id}")

    async def explain_1c_syntax(self, request: ExplainSyntaxRequest) -> ResponseModel:
        await self._initialize_client()

        if not request.syntax_element.strip():
            return ResponseModel(result="", error="Элемент синтаксиса не может быть пустым")

        question = f"Объясни синтаксис и использование: {request.syntax_element}"
        if request.context:
            question += f" в контексте: {request.context}"

        conversation_id = await self.api_client.get_or_create_session()
        answer = await self.api_client.send_message(conversation_id, question)
        clean_answer = self._sanitize_text(answer)

        return ResponseModel(result=f"Объяснение синтаксиса '{request.syntax_element}':\n\n{clean_answer}")

    async def check_1c_code(self, request: CheckCodeRequest) -> ResponseModel:
        await self._initialize_client()

        if not request.code.strip():
            return ResponseModel(result="", error="Код для проверки не может быть пустым")

        check_types = {
            "syntax": "синтаксические ошибки",
            "logic": "логические ошибки и потенциальные проблемы",
            "performance": "проблемы производительности и оптимизации"
        }
        check_desc = check_types.get(request.check_type.lower(), "ошибки")

        question = f"Проверь этот код 1С на {check_desc} и дай рекомендации:\n\n```1c\n{request.code}\n```"

        conversation_id = await self.api_client.get_or_create_session()
        answer = await self.api_client.send_message(conversation_id, question)
        clean_answer = self._sanitize_text(answer)

        return ResponseModel(result=f"Проверка кода на {check_desc}:\n\n{clean_answer}")


# --- FastAPI приложение ---
app = FastAPI(
    title="1С.ai REST API",
    description="REST-интерфейс для вызова инструментов 1С.ai: проверка кода, объяснение синтаксиса и AI-вопросы.",
    version="1.0.0"
)

server = OneCRestServer()


@app.post("/ask-ai", response_model=ResponseModel)
async def api_ask_ai(request: AskAIRequest):
    try:
        return await server.ask_1c_ai(request)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Неожиданная ошибка в /ask-ai: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@app.post("/explain-syntax", response_model=ResponseModel)
async def api_explain_syntax(request: ExplainSyntaxRequest):
    try:
        return await server.explain_1c_syntax(request)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Неожиданная ошибка в /explain-syntax: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@app.post("/check-code", response_model=ResponseModel)
async def api_check_code(request: CheckCodeRequest):
    try:
        return await server.check_1c_code(request)
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Неожиданная ошибка в /check-code: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "services": ["1C.ai API"]}


@app.get("/")
async def root():
    return {
        "message": "Добро пожаловать в 1С.ai REST API",
        "endpoints": {
            "/ask-ai": "Задать вопрос ИИ",
            "/explain-syntax": "Объяснить синтаксис 1С",
            "/check-code": "Проверить код на ошибки",
            "/health": "Проверка статуса",
            "/docs": "Документация Swagger UI"
        }
    }


if __name__ == "__main__":
    logger.info("🚀 Запуск 1С.ai REST API сервера на http://localhost:8000")
    uvicorn.run(
        "onec_rest_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

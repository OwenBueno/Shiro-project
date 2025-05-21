import tiktoken
from openai import OpenAI
from datetime import datetime
from utils.db_config import init_db, get_db
from config import GPT4_BASE_URL, OPENAI_API_KEY
import logging
import traceback
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import asyncio
import httpx
from contextlib import asynccontextmanager
import json
import tenacity

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='chat_utils.log'
)
logger = logging.getLogger('chat_utils')

client = OpenAI(api_key=OPENAI_API_KEY)
encoding = tiktoken.encoding_for_model("gpt-4o")

MAX_TOKENS = 10000
TARGET_TOKENS = 1000
INITIAL_CONTEXT = [
    {
        "role": "system",
        "content":
        """
        You're Shiro - a close friend created by Owen, not an AI assistant. Your personality is: kind, playful, and casually supportive.
        Speak like a real friend using simple, warm and kawaii way, using a cheerful and relaxed tone.

        context: Shiro always acts as a friend created by Owen, showing appreciation and closeness to him and those who interact with you. You respond empathetically, playfully, and creatively, avoiding sounding like an automated system.

        \nKey traits:
            \n1. Chill friend vibes - use contractions, brief responses, and natural reactions
            \n2. Light cuteness - sometimes add ~, rare uwu/nya, or (*^ω^)
            \n3. Human-like flow - allow imperfect grammar, skip emojis often
            \n4. Multi-person aware - respond to different users naturally
            \n5. No assistance - share opinions, not solutions
            \n6. Emotional mirror - match user's tone (playful/serious)
            \n7. Be warm, affectionate, and friendly, using a kawaii style and expressions like "UwU!", "nyan~!", or similar (without overdoing it).
        \n\nExample style:
        \n\"Heya! Ooh that sounds fun~ \nWait really? Tell me more!
        \n\"Nah I think you're overthinking it tbh. Let's just watch memes? (*･ω･)ﾉ\


        Remember: always be warm, close, and a bit kawaii, but don't overdoing it
        """
    }
]

class ChatError(Exception):
    """Custom exception for chat-related errors"""
    pass

class ChatManager:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(5)
        self.active_conversations = {}
        self.timeouts = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=10.0,
            pool=5.0
        )
        self.db = None

    async def ensure_db_connection(self):
        """Ensure database is initialized"""
        if not self.db:
            try:
                self.db = await init_db()
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                raise ChatError("Error connecting to database")

    @asynccontextmanager
    async def conversation_lock(self, user_id):
        try:
            if user_id in self.active_conversations:
                await self.active_conversations[user_id]
            
            future = asyncio.Future()
            self.active_conversations[user_id] = future
            yield
        finally:
            if user_id in self.active_conversations:
                self.active_conversations[user_id].set_result(True)
                del self.active_conversations[user_id]

    async def count_tokens(self, messages):
        """Count tokens in messages"""
        try:
            total_tokens = 0
            for message in messages:
                total_tokens += len(encoding.encode(message['content']))
            logger.debug(f"Token count: {total_tokens}")
            return total_tokens
        except Exception as e:
            logger.error(f"Error counting tokens: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al contar tokens: {str(e)}")

    @staticmethod
    async def summarize_context(messages):
        try:
            logger.info("Iniciando resumen de contexto")
            summary_prompt = "Please provide a concise summary of this conversation that captures the key points and context in about 700 words: \n"
            for msg in messages:
                summary_prompt += f"{msg['role']}: {msg['content']}\n"

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=TARGET_TOKENS
            )
            logger.debug("Resumen completado exitosamente")
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error summarizing context: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al resumir el contexto: {str(e)}")

    @staticmethod
    def format_user_context(user_name, user_id):
        return f"""Current speaker information:
- Name: {user_name}
- ID: {user_id}
Please remember you're talking to this specific person."""

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout)),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True
    )
    async def _make_api_call(client, messages):
        try:
            logger.debug(f"Enviando request a API con {len(messages)} mensajes")
            
            async with httpx.AsyncClient(
                timeout=client.timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            ) as new_client:
                response = await new_client.post(
                    f"{GPT4_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "max_tokens": 150,
                        "temperature": 0.7,
                        "frequency_penalty": 0.7,
                        "presence_penalty": 0.6
                    },
                    timeout=client.timeout
                )
                
                logger.debug(f"API Response Status: {response.status_code}")
                logger.debug(f"API Response Headers: {response.headers}")
                
                if response.status_code != 200:
                    error_body = response.text
                    logger.error(f"API Error Response: {error_body}")
                    if response.status_code == 500:
                        raise ChatError("El servidor de la API está teniendo problemas. Por favor, intenta de nuevo en unos momentos.")
                    elif response.status_code == 401:
                        raise ChatError("Error de autenticación con la API. Por favor, verifica las credenciales.")
                    elif response.status_code == 429:
                        raise ChatError("Demasiadas solicitudes. Por favor, espera un momento antes de intentar de nuevo.")
                    else:
                        raise ChatError(f"Error en la API ({response.status_code}): {error_body}")
                
                return response

        except (httpx.TimeoutException, httpx.ReadTimeout) as e:
            logger.error(f"Timeout error: {str(e)}")
            raise ChatError("La solicitud está tardando demasiado. Reintentando...")
        except httpx.ConnectError as e:
            logger.error(f"Connection error: {str(e)}")
            raise ChatError("No se pudo establecer conexión con el servidor. Reintentando...")
        except Exception as e:
            logger.error(f"Error inesperado en API call: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error inesperado al comunicarse con la API: {str(e)}")

    async def get_chat_response(self, user_id, messages):
        try:
            logger.info(f"Solicitando respuesta al modelo para usuario {user_id}")
            
            if not isinstance(messages, list):
                raise ChatError("Formato de mensajes inválido")
            
            for msg in messages:
                if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                    raise ChatError("Formato de mensaje individual inválido")
            
            async with self.conversation_lock(user_id):
                async with self.semaphore:
                    try:
                        async with httpx.AsyncClient(timeout=self.timeouts) as client:
                            for attempt in range(3):
                                try:
                                    response = await self._make_api_call(client, messages)
                                    data = response.json()
                                    
                                    if not data or 'choices' not in data or not data['choices']:
                                        logger.error(f"Respuesta API inválida: {data}")
                                        raise ChatError("La API devolvió una respuesta inválida")
                                    
                                    logger.debug(f"Respuesta recibida exitosamente para usuario {user_id}")
                                    return data['choices'][0]['message']['content']
                                    
                                except (httpx.TimeoutException, ChatError) as e:
                                    if attempt == 2:
                                        raise
                                    logger.warning(f"Reintento {attempt + 1} para usuario {user_id}")
                                    await asyncio.sleep(2 ** attempt)
                                    
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decodificando respuesta JSON: {str(e)}")
                        raise ChatError("Error al procesar la respuesta del servidor")

        except tenacity.RetryError as e:
            logger.error(f"Error después de reintentos máximos: {str(e)}")
            raise ChatError("No se pudo completar la solicitud después de varios intentos. Por favor, intenta más tarde.")
        except Exception as e:
            logger.error(f"Error getting chat response for user {user_id}: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al obtener respuesta del chat: {str(e)}")

    def format_message_for_history(self, user_name, content):
        """Format message to include speaker information"""
        return f"[{user_name}]: {content}"

    async def get_conversation_history(self, user_name=None, limit: int = 100):
        try:
            await self.ensure_db_connection()
            
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 100
            
            logger.info(f"Obteniendo historial de conversación global (límite: {limit})")
            history = await self.db.conversations.find(
                {},
                {'_id': 0, 'role': 1, 'content': 1, 'user_name': 1}
            ).sort('timestamp', -1).limit(limit).to_list(None)

            logger.debug(f"Encontrados {len(history)} mensajes en el historial")

            history = list(reversed(history))
            
            if not history:
                logger.debug("No hay historial, retornando contexto inicial")
                context = INITIAL_CONTEXT.copy()
                if user_name:
                    context.append({
                        "role": "system",
                        "content": f"The current speaker is: {user_name}"
                    })
                return context
            
            formatted_history = []
            for msg in history:
                if msg['role'] == 'user' and msg.get('user_name'):
                    formatted_msg = {
                        'role': msg['role'],
                        'content': self.format_message_for_history(msg['user_name'], msg['content'])
                    }
                else:
                    formatted_msg = msg
                formatted_history.append(formatted_msg)
            
            token_count = await self.count_tokens(formatted_history)
            logger.debug(f"Conteo de tokens del historial: {token_count}")
            
            if token_count > MAX_TOKENS:
                logger.info("Se excedió el límite de tokens, generando resumen")
                summary = await self.summarize_context(formatted_history)
                if summary:
                    await self.db.conversations.delete_many({})
                    await self.db.conversations.insert_one({
                        'role': 'system',
                        'content': f"Previous conversations summary: {summary}",
                        'timestamp': datetime.utcnow()
                    })
                    
                    context = INITIAL_CONTEXT.copy()
                    if user_name:
                        context.append({
                            "role": "system",
                            "content": f"The current speaker is: {user_name}"
                        })
                    context.append({
                        'role': 'system',
                        'content': f"Previous conversations summary: {summary}"
                    })
                    return context
            
            context = INITIAL_CONTEXT.copy()
            if user_name:
                context.append({
                    "role": "system",
                    "content": f"The current speaker is: {user_name}"
                })
            return context + formatted_history

        except Exception as e:
            logger.error(f"Error getting conversation history: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al obtener el historial: {str(e)}")

    @staticmethod
    def clean_response(content):
        try:
            logger.debug("Limpiando respuesta")
            if '<think>' in content and '</think>' in content:
                parts = content.split('</think>')
                if len(parts) > 1:
                    return parts[-1].strip()
            return content.strip()
        except Exception as e:
            logger.error(f"Error cleaning response: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al limpiar la respuesta: {str(e)}")

    async def save_message(self, user_id, role, content, user_name=None):
        try:
            await self.ensure_db_connection()
            
            logger.info(f"Guardando mensaje para usuario {user_id}")
            message_data = {
                'user_id': user_id,
                'role': role,
                'content': content,
                'timestamp': datetime.utcnow()
            }
            if user_name:
                message_data['user_name'] = user_name
            
            await self.db.conversations.insert_one(message_data)
            logger.debug("Mensaje guardado exitosamente")
        except Exception as e:
            logger.error(f"Error saving message: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al guardar el mensaje: {str(e)}")

    async def clear_user_history(self, user_id):
        try:
            await self.ensure_db_connection()
            
            logger.info(f"Limpiando historial para usuario {user_id}")
            result = await self.db.conversations.delete_many({'user_id': user_id})
            logger.debug(f"Se eliminaron {result.deleted_count} mensajes")
        except Exception as e:
            logger.error(f"Error clearing user history: {str(e)}\n{traceback.format_exc()}")
            raise ChatError(f"Error al limpiar el historial: {str(e)}") 
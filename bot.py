import os
import sys
import asyncio
import json
import telebot
import requests
import uuid
from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

TOKEN = os.getenv("TOKEN")
ELEVEN_LABS_API_KEY = os.getenv("ELEVEN_LABS_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3000")

bot = telebot.TeleBot(TOKEN)
elevenlabs = ElevenLabs(api_key=ELEVEN_LABS_API_KEY)

sessions = {}

# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER_SCRIPT = os.path.abspath(os.path.join(_script_dir, "../hacker-shop-server/mcp_server.py"))
_venv_python = os.path.abspath(os.path.join(_script_dir, "../hacker-shop-server/.venv/Scripts/python.exe"))
MCP_PYTHON = _venv_python if os.path.exists(_venv_python) else sys.executable


async def _call_mcp(tool_name: str, args: dict = None) -> any:
    server_params = StdioServerParameters(command=MCP_PYTHON, args=[MCP_SERVER_SCRIPT])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args or {})
            if result.content:
                content = result.content[0]
                text = content.text if hasattr(content, "text") else str(content)
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    return text
    return None


def call_mcp(tool_name: str, args: dict = None) -> any:
    return asyncio.run(_call_mcp(tool_name, args))


def _format_product_list(products: list) -> str:
    lines = []
    for p in products:
        stock = int(p.get("stock", 0))
        price = float(str(p.get("price", 0)))
        status = "✅" if stock > 0 else "❌"
        desc = (p.get("description") or "")[:80]
        entry = f"{status} *{p['name']}*\n  💰 `${price:.2f}` | Stock: {stock}"
        if desc:
            entry += f"\n  _{desc}_"
        lines.append(entry)
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Session / AI helpers
# ---------------------------------------------------------------------------

def get_session(user_id: int) -> dict:
    if user_id not in sessions:
        sessions[user_id] = {
            "session_id": str(uuid.uuid4()),
            "history": []
        }
    return sessions[user_id]

def send_to_ai(message: str, user_id: int) -> str:
    session = get_session(user_id)

    try:
        response = requests.post(
            f"{BACKEND_URL}/ai/chat",
            json={"message": message, "sessionId": session["session_id"]},
            headers={"Content-Type": "application/json"},
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            session["session_id"] = data.get("sessionId", session["session_id"])
            return data.get("response", "No response from AI")
        else:
            return f"Error: Backend returned status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to backend server. Make sure it's running on port 3000."
    except Exception as e:
        return f"Error: {str(e)}"

def speech_to_text(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            result = elevenlabs.speech_to_text.convert(
                file=f,
                model_id="scribe_v2"
            )
        return result.text
    except Exception as e:
        return f"Error converting speech to text: {str(e)}"

def download_file(file_id: str, file_name: str) -> str:
    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)

        with open(file_name, "wb") as f:
            f.write(downloaded)
        return file_name
    except Exception as e:
        print(f"Error downloading file: {e}")
        return None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["products"])
def handle_products(message):
    msg = bot.send_message(message.chat.id, "⏳ Fetching products...")
    try:
        products = call_mcp("list_products")
        if isinstance(products, list) and products:
            text = "🛒 *Hacker Shop — Products:*\n\n" + _format_product_list(products)
        elif isinstance(products, list):
            text = "No products found in the shop."
        else:
            text = f"Unexpected response: {products}"
        bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Error fetching products: {str(e)}", message.chat.id, msg.message_id)


@bot.message_handler(commands=["categories"])
def handle_categories(message):
    msg = bot.send_message(message.chat.id, "⏳ Fetching categories...")
    try:
        categories = call_mcp("list_categories")
        if isinstance(categories, list) and categories:
            lines = ["📂 *Categories:*\n"]
            for c in categories:
                lines.append(f"• {c['name']}")
            text = "\n".join(lines)
        elif isinstance(categories, list):
            text = "No categories found."
        else:
            text = f"Unexpected response: {categories}"
        bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Error fetching categories: {str(e)}", message.chat.id, msg.message_id)


@bot.message_handler(commands=["search"])
def handle_search(message):
    query = message.text.partition(" ")[2].strip()
    if not query:
        bot.reply_to(message, "Usage: /search <product name or keyword>")
        return
    msg = bot.send_message(message.chat.id, f"🔍 Searching for *{query}*...", parse_mode="Markdown")
    try:
        products = call_mcp("search_products", {"query": query})
        if isinstance(products, list) and products:
            text = f"🔍 *Search results for \"{query}\":*\n\n" + _format_product_list(products)
        elif isinstance(products, list):
            text = f"No products found matching *{query}*."
        else:
            text = f"Unexpected response: {products}"
        bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Error searching products: {str(e)}", message.chat.id, msg.message_id)


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    bot.send_message(message.chat.id, "🎤 Processing your voice message...")

    file_id = message.voice.file_id
    ogg_path = f"voice_{message.from_user.id}_{message.message_id}.ogg"
    mp3_path = f"voice_{message.from_user.id}_{message.message_id}.mp3"

    try:
        ogg_path = download_file(file_id, ogg_path) or ogg_path

        import subprocess
        import imageio_ffmpeg
        ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg_cmd, "-y", "-i", ogg_path, mp3_path], check=True, capture_output=True)

        text = speech_to_text(mp3_path)

        os.remove(ogg_path)
        os.remove(mp3_path)

        if text.startswith("Error"):
            bot.reply_to(message, text)
            return

        bot.reply_to(message, f"🎙 Transcribed: \"{text}\"")

        bot.send_message(message.chat.id, "🤖 AI is thinking...")
        response = send_to_ai(text, message.from_user.id)
        bot.reply_to(message, response)

    except FileNotFoundError:
        bot.reply_to(message, "❌ ffmpeg not found. Please install ffmpeg to process voice messages.")
    except Exception as e:
        bot.reply_to(message, f"Error processing voice: {str(e)}")

@bot.message_handler(content_types=["text"])
def handle_text(message):
    if message.text.startswith("/"):
        return

    bot.send_message(message.chat.id, "🤖 AI is thinking...")
    response = send_to_ai(message.text, message.from_user.id)
    bot.reply_to(message, response)

@bot.message_handler(commands=["start", "help"])
def handle_help(message):
    help_text = """🤖 Hacker Shop AI Assistant

Shop commands (direct MCP access):
/products — list all available products
/categories — list all product categories
/search <query> — search products by name or description

AI chat:
Send any text or voice message to ask the AI assistant about products, orders, or anything else.

Other:
/start — show this help
/clear — clear your chat history
"""
    bot.reply_to(message, help_text)

@bot.message_handler(commands=["clear"])
def handle_clear(message):
    user_id = message.from_user.id
    if user_id in sessions:
        del sessions[user_id]
    bot.reply_to(message, "🗑️ Chat history cleared!")

if __name__ == "__main__":
    print("🚀 Hacker Shop Telegram Bot is starting...")
    bot.infinity_polling()

import os
import telebot
import requests
import json
import uuid
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

load_dotenv()

TOKEN = os.getenv("TOKEN")
ELEVEN_LABS_API_KEY = os.getenv("ELEVEN_LABS_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3000")

bot = telebot.TeleBot(TOKEN)
elevenlabs = ElevenLabs(api_key=ELEVEN_LABS_API_KEY)

sessions = {}

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

@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    bot.send_message(message.chat.id, "🎤 Processing your voice message...")
    
    file_id = message.voice.file_id
    ogg_path = f"voice_{message.from_user.id}_{message.message_id}.ogg"
    mp3_path = f"voice_{message.from_user.id}_{message.message_id}.mp3"
    
    try:
        ogg_path = download_file(file_id, ogg_path) or ogg_path
        
        import subprocess
        ffmpeg_cmd = "ffmpeg.exe" if os.path.exists("ffmpeg.exe") else "ffmpeg"
        subprocess.run([ffmpeg_cmd, "-y", "-i", ogg_path, mp3_path], check=True, capture_output=True)
        
        text = speech_to_text(mp3_path)
        
        os.remove(ogg_path)
        os.remove(mp3_path)
        
        if text.startswith("Error"):
            bot.reply_to(message, text)
            return
            
        bot.reply_to(message, f"��� Transcribed: \"{text}\"")
        
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

I can help you with:
• Questions about products
• Product search and details
• Category information
• Order inquiries

Send me a text message or a voice message!

Commands:
/start - Show this help
/clear - Clear your chat history
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
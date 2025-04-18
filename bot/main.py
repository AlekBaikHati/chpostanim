import logging
import os
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import telegram
import asyncio
import random
import time
from bot.utilities.http_server import run_http_server  # Import server HTTP jika diperlukan
import nest_asyncio
import re
import threading

# Muat variabel lingkungan dari .env
load_dotenv()

# Konfigurasi bot
API_TOKEN = os.getenv('API_TOKEN')
CH_KOLEKSI = os.getenv('CH_KOLEKSI')  # Bisa berupa ID atau @username
CH_POST = os.getenv('CH_POST')  # Bisa berupa ID atau @username
DEFAULT_TITLE = os.getenv('DEFAULT_TITLE')
DEFAULT_PHOTO_URL = os.getenv('DEFAULT_PHOTO_URL')
ALLOWED_USERS = set(map(int, os.getenv('ALLOWED_USERS', '').split(',')))

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Fungsi untuk mendapatkan gambar anime acak dari API
async def get_random_anime_image():
    random_param = random.randint(0, 1000000)
    response = requests.get(f"https://pic.re/image?random={random_param}")
    if response.status_code == 200:
        return response.url
    return None

# Fungsi untuk menangani perintah /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start_message = (
        "👋 Selamat datang di Bot Koleksi Anime!\n\n"
        "📋 Cara menggunakan bot ini:\n"
        "1️⃣ Kirimkan pesan yang berisi link.\n"
        "2️⃣ Pilih judul default atau masukkan judul manual.\n"
        "3️⃣ Pilih gambar yang ingin diposting.\n"
        "4️⃣ Tekan 'Post' untuk memposting ke channel.\n\n"
        "⚠️ Bot ini hanya dapat digunakan oleh admin yang terdaftar."
    )
    sent_message = await update.message.reply_text(start_message)
    await asyncio.sleep(5)  # Tunggu 5 detik
    try:
        await sent_message.delete()  # Hapus pesan
    except telegram.error.BadRequest:
        pass  # Pesan mungkin sudah dihapus

# Fungsi untuk memulai bot dengan menampilkan gambar anime acak
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message:
        # Log entitas dalam pesan
        logger.info(f"Entities: {message.entities}")
        logger.info(f"Caption Entities: {message.caption_entities}")

        # Abaikan pesan yang bukan dari chat pribadi
        if message.chat.type != 'private':
            return

        # Cek apakah pengguna adalah admin
        if update.effective_user.id not in ALLOWED_USERS:
            await message.reply_text("🚫 Maaf, Anda tidak diizinkan menggunakan bot ini.")
            return

        # Cek apakah bot sedang memproses permintaan lain
        if context.user_data.get('processing', False):
            # Hapus pesan pengguna
            await message.delete()
            sent_message = await message.reply_text("⏳ Proses sedang berjalan. Lanjutkan proses sebelumnya atau batalkan.")
            await asyncio.sleep(3)
            await sent_message.delete()
            return

        # Fungsi untuk mengekstrak URL dari entitas
        def extract_urls(entities, text):
            urls = []
            if entities:
                for entity in entities:
                    if entity.type == "url":
                        urls.append(text[entity.offset:entity.offset + entity.length])
            return urls

        # Periksa semua entitas dalam pesan untuk menemukan URL
        urls = extract_urls(message.entities, message.text or "") + extract_urls(message.caption_entities, message.caption or "")

        if urls:
            # Hapus pesan pengguna
            await message.delete()
            context.user_data['link'] = urls[0]  # Simpan link
            context.user_data['processing'] = True  # Set flag processing
            sent_message = await message.reply_text(
                "📝 Silakan kirimkan judul untuk link ini.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📌 JUDUL DEFAULT", callback_data='default_title')],
                    [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
                ])
            )
            context.user_data['sent_message_id'] = sent_message.message_id  # Simpan ID pesan
        else:
            await message.reply_text("❗ Tidak ada link yang ditemukan dalam pesan.")
    else:
        logger.info("menerima pesan dari channel abaikan saja")

# Fungsi untuk menangani pesan teks yang berisi judul
async def handle_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title = update.message.text
    if 'link' in context.user_data:
        # Hapus pesan pengguna dan pesan permintaan judul
        await update.message.delete()
        if 'sent_message_id' in context.user_data:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data['sent_message_id'])
            except telegram.error.BadRequest:
                pass  # Pesan mungkin sudah dihapus

        # Ubah judul menjadi huruf kapital dan tebal, dan tambahkan emoji
        formatted_title = f"🏷 *{title.upper()}*"
        context.user_data['title'] = formatted_title  # Simpan judul yang sudah diformat
        # Gunakan foto default pertama kali
        context.user_data['images'] = [DEFAULT_PHOTO_URL]
        context.user_data['current_index'] = 0
        # Escape karakter yang diperlukan untuk Markdown V2
        link = context.user_data['link']
        link = re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', link)  # Escape karakter khusus
        caption = f"{formatted_title}\n\n>{link}\n"  # Gabungkan judul dan link dengan blockquote dan dua garis baru
        keyboard = create_mode_keyboard(0)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_photo(photo=DEFAULT_PHOTO_URL, caption=caption, reply_markup=reply_markup, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
        # Jangan kirim foto default ke CH_KOLEKSI
    else:
        await update.message.reply_text("⚠️ Gagal mendapatkan gambar. Coba lagi nanti.")

# Fungsi untuk menangani tombol
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    images = context.user_data.get('images', [])
    current_index = context.user_data.get('current_index', 0)
    title = context.user_data.get('title', "No title available")
    link = context.user_data.get('link', "No link available")
    
    # Escape karakter yang diperlukan untuk Markdown V2
    link = re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', link)  # Escape karakter khusus
    caption = f"{title}\n\n>{link}\n"  # Pastikan newline ada di sini

    if data == 'default_title':
        # Hapus pesan permintaan judul
        if 'sent_message_id' in context.user_data:
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=context.user_data['sent_message_id'])
            except telegram.error.BadRequest:
                pass  # Pesan mungkin sudah dihapus

        # Set judul default dan escape karakter khusus
        default_title = DEFAULT_TITLE
        context.user_data['title'] = default_title
        # Gunakan foto default pertama kali
        context.user_data['images'] = [DEFAULT_PHOTO_URL]
        context.user_data['current_index'] = 0
        caption = f"{default_title}\n\n>{link}\n"
        keyboard = create_mode_keyboard(0)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_photo(photo=DEFAULT_PHOTO_URL, caption=caption, reply_markup=reply_markup, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
        # Jangan kirim foto default ke CH_KOLEKSI
    elif data == 'next':
        if current_index < len(images) - 1:
            current_index += 1
        else:
            image_url = await get_random_anime_image()
            if image_url:
                images.append(image_url)
                current_index += 1
                # Kirim ke CH_KOLEKSI tanpa caption
                koleksi_message = await context.bot.send_photo(chat_id=CH_KOLEKSI, photo=image_url)
                context.user_data['koleksi_message_id'] = koleksi_message.message_id  # Simpan ID pesan koleksi
        
        context.user_data['current_index'] = current_index
        image_url = images[current_index]
        await query.message.edit_media(
            media=telegram.InputMediaPhoto(media=image_url, caption=caption, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2),
            reply_markup=InlineKeyboardMarkup(create_mode_keyboard(current_index))
        )
    elif data == 'back' and current_index > 0:
        current_index -= 1
        context.user_data['current_index'] = current_index
        image_url = images[current_index]
        await query.message.edit_media(
            media=telegram.InputMediaPhoto(media=image_url, caption=caption, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2),
            reply_markup=InlineKeyboardMarkup(create_mode_keyboard(current_index))
        )
    elif data == 'post':
        image_url = images[current_index]
        message = await context.bot.send_photo(chat_id=CH_POST, photo=image_url, caption=caption, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
        
        # Buat link postingan berdasarkan format yang tepat
        if CH_POST.startswith('@'):
            post_link = f"https://t.me/{CH_POST.lstrip('@')}/{message.message_id}"
        else:
            # Jika CH_POST adalah ID channel, hapus '-100' dari ID
            channel_id = CH_POST.lstrip('-100')
            post_link = f"https://t.me/c/{channel_id}/{message.message_id}"
        
        # Buat link koleksi berdasarkan format yang tepat
        if CH_KOLEKSI.startswith('@'):
            koleksi_link = f"https://t.me/{CH_KOLEKSI.lstrip('@')}/{context.user_data.get('koleksi_message_id', '')}"
        else:
            # Jika CH_KOLEKSI adalah ID channel, hapus '-100' dari ID
            koleksi_channel_id = CH_KOLEKSI.lstrip('-100')
            koleksi_link = f"https://t.me/c/{koleksi_channel_id}/{context.user_data.get('koleksi_message_id', '')}"
        
        await query.message.edit_caption(
            caption="✅ SUKSES POST",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 LIHAT CH POSTINGAN", url=post_link)],
                [InlineKeyboardButton("🔗 LIHAT CH KOLEKSI", url=koleksi_link)],
                [InlineKeyboardButton("❌ Cancel", callback_data='close')]
            ])
        )
        # Reset flag processing setelah posting selesai
        context.user_data['processing'] = False
    elif data == 'close' or data == 'cancel':
        await query.message.delete()
        context.user_data['processing'] = False  # Reset flag processing jika dibatalkan

# Fungsi untuk membuat keyboard mode
def create_mode_keyboard(current_index: int) -> list:
    keyboard = []
    if current_index > 0:
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='back'), InlineKeyboardButton("➡️ Next", callback_data='next')])
    else:
        keyboard.append([InlineKeyboardButton("➡️ Next", callback_data='next')])
    keyboard.append([InlineKeyboardButton("📤 Post", callback_data='post')])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='close')])
    return keyboard

# Fungsi untuk menjalankan server HTTP di thread terpisah
def start_http_server():
    server_thread = threading.Thread(target=run_http_server)
    server_thread.daemon = True
    server_thread.start()

async def main() -> None:
    # Mulai server HTTP
    start_http_server()  # Panggil server HTTP

    application = Application.builder().token(API_TOKEN).build()
    application.add_handler(CommandHandler("start", start))  # Tambahkan handler untuk /start
    application.add_handler(MessageHandler(filters.TEXT & filters.Entity("url"), handle_message))  # Tambahkan handler untuk pesan teks yang berisi URL
    application.add_handler(MessageHandler(filters.PHOTO & filters.Entity("url"), handle_message))  # Tambahkan handler untuk pesan foto yang berisi URL di caption
    application.add_handler(MessageHandler(filters.TEXT & ~filters.Entity("url"), handle_title))  # Tambahkan handler untuk pesan teks yang tidak berisi URL
    application.add_handler(MessageHandler(filters.FORWARDED & filters.Entity("url"), handle_message))  # Tambahkan handler untuk pesan diteruskan yang berisi URL
    application.add_handler(CallbackQueryHandler(button))
    logger.info("Bot dimulai dan siap menerima pesan.")
    await application.run_polling()
    logger.info("Bot dihentikan.")

if __name__ == '__main__':
    try:
        nest_asyncio.apply()
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot dihentikan oleh pengguna.")

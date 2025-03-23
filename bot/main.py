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

# Muat variabel lingkungan dari .env
load_dotenv()

# Konfigurasi bot
API_TOKEN = os.getenv('API_TOKEN')
CH_KOLEKSI = os.getenv('CH_KOLEKSI')  # Bisa berupa ID atau @username
CH_POST = os.getenv('CH_POST')  # Bisa berupa ID atau @username

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

# Fungsi untuk memulai bot dengan menampilkan gambar anime acak
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message:
        # Abaikan pesan yang bukan dari chat pribadi
        if message.chat.type != 'private':
            return

        # Cek apakah bot sedang memproses permintaan lain
        if context.user_data.get('processing', False):
            sent_message = await message.reply_text("Proses sedang berjalan. Tunggu atau batalkan.")
            # Hapus pesan setelah 3 detik
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
            context.user_data['link'] = urls[0]  # Simpan link
            context.user_data['processing'] = True  # Set flag processing
            await message.reply_text(
                "Silakan kirimkan judul untuk link ini.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='cancel')]])
            )
        else:
            await message.reply_text("Tidak ada link yang ditemukan dalam pesan.")
    else:
        logger.info("menerima pesan dari channel abaikan saja")

# Fungsi untuk menangani pesan teks yang berisi judul
async def handle_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title = update.message.text
    if 'link' in context.user_data:
        # Ubah judul menjadi huruf kapital dan tebal, dan tambahkan emoji
        formatted_title = f"🏷 *{title.upper()}*"
        context.user_data['title'] = formatted_title  # Simpan judul yang sudah diformat
        image_url = await get_random_anime_image()
        if image_url:
            context.user_data['images'] = [image_url]  # Simpan URL gambar dalam list
            context.user_data['current_index'] = 0  # Set indeks saat ini ke 0
            # Escape karakter yang diperlukan untuk Markdown V2
            link = context.user_data['link']
            link = re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', link)  # Escape karakter khusus
            caption = f"{formatted_title}\n\n>{link}\n"  # Gabungkan judul dan link dengan blockquote dan dua garis baru
            keyboard = create_mode_keyboard(0)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_photo(photo=image_url, caption=caption, reply_markup=reply_markup, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
            # Kirim ke CH_KOLEKSI
            await context.bot.send_photo(chat_id=CH_KOLEKSI, photo=image_url, caption=caption, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
    else:
            await update.message.reply_text("Gagal mendapatkan gambar. Coba lagi nanti.")
    else:
        await update.message.reply_text("Tidak ada link yang disimpan. Kirimkan link terlebih dahulu.")

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
    caption = f"{title}\n>{link}"

    if data == 'next':
        if current_index < len(images) - 1:
            current_index += 1
        else:
            image_url = await get_random_anime_image()
            if image_url:
                images.append(image_url)
                current_index += 1
                # Kirim ke CH_KOLEKSI
                await context.bot.send_photo(chat_id=CH_KOLEKSI, photo=image_url, caption=caption, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)
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
        
        await query.message.edit_caption(
            caption="SUKSES POST",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("LIHAT POSTINGAN", url=post_link)],
                [InlineKeyboardButton("Cancel", callback_data='close')]
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
        keyboard.append([InlineKeyboardButton("Back", callback_data='back'), InlineKeyboardButton("Next", callback_data='next')])
            else:
        keyboard.append([InlineKeyboardButton("Next", callback_data='next')])
    keyboard.append([InlineKeyboardButton("Post", callback_data='post')])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data='close')])
    return keyboard

async def main() -> None:
    # Mulai server HTTP jika diperlukan
    # run_http_server()

    application = Application.builder().token(API_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & filters.Entity("url"), handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.Entity("url"), handle_title))
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

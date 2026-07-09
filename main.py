"""
Bot Telegram: Asisten Nutrisi Sehat & Murah ala Indonesia
=========================================================
Fitur:
  - Registrasi alergi manual via /alergi [bahan1, bahan2]
  - Konsultasi kesehatan via pesan teks biasa
  - Rekomendasi menu lokal murah dari Gemini AI dengan filter alergi ketat
  - Pengingat otomatis 10 detik setelah konsultasi (simulasi reminder)
  - Penyimpanan data pengguna permanen di SQLite
"""

import logging
import sqlite3
import os
import re
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from google import genai
from google.genai import types

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Konfigurasi Token (dari Environment Variables)
# ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Environment variable TELEGRAM_TOKEN belum diset!")
if not GEMINI_API_KEY:
    raise RuntimeError("Environment variable GEMINI_API_KEY belum diset!")

# ──────────────────────────────────────────────
# Inisialisasi Gemini Client
# ──────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ──────────────────────────────────────────────
# SQLite — Inisialisasi Database
# ──────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "bot_data.db"


def init_db() -> None:
    """Membuat tabel users jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            alergi     TEXT    DEFAULT 'Tidak ada',
            menu       TEXT    DEFAULT '',
            reminder   INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()
    logger.info("Database SQLite siap digunakan.")


def get_or_create_user(user_id: int) -> dict:
    """Mengambil data user; buat baris baru jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, alergi, menu, reminder FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = (user_id, "Tidak ada", "", 0)
    conn.close()
    return {
        "user_id": row[0],
        "alergi": row[1],
        "menu": row[2],
        "reminder": row[3],
    }


def update_alergi(user_id: int, alergi: str) -> None:
    """Memperbarui daftar alergi pengguna di database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET alergi = ? WHERE user_id = ?", (alergi, user_id))
    conn.commit()
    conn.close()


def update_menu(user_id: int, menu: str) -> None:
    """Menyimpan nama menu rekomendasi terakhir ke database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET menu = ?, reminder = 1 WHERE user_id = ?", (menu, user_id))
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# Helper — Bersihkan teks alergi
# ──────────────────────────────────────────────
def bersihkan_alergi(teks: str) -> str:
    """Ubah ke huruf kecil, hapus spasi berlebih, rapikan koma."""
    teks = teks.lower().strip()
    # Pisah berdasarkan koma, bersihkan tiap item, gabungkan kembali
    items = [item.strip() for item in teks.split(",") if item.strip()]
    return ", ".join(items)


# ──────────────────────────────────────────────
# Helper — Ekstrak nama menu dari respons Gemini
# ──────────────────────────────────────────────
def ekstrak_nama_menu(respons: str) -> str:
    """Mengambil nama menu dari baris 'Menu: ...' di respons Gemini."""
    match = re.search(r"Menu\s*:\s*(.+)", respons)
    if match:
        return match.group(1).strip()
    return "Menu Sehat Hari Ini"


# ──────────────────────────────────────────────
# Bangun System Instruction dinamis untuk Gemini
# ──────────────────────────────────────────────
def bangun_system_instruction(alergi: str) -> str:
    """Membuat system instruction Gemini yang menyertakan data alergi pengguna."""

    instruksi = (
        "Kamu adalah seorang Dokter & Ahli Gizi Ramah Indonesia yang sangat berpengalaman. "
        "Tugasmu adalah memberikan rekomendasi menu makanan sehat untuk mengatasi keluhan "
        "kesehatan pengguna.\n\n"
        "## ATURAN MUTLAK YANG WAJIB DIPATUHI:\n\n"
        "### 1. MENU HARUS MURAH & LOKAL INDONESIA\n"
        "- WAJIB gunakan bahan makanan lokal Indonesia yang terjangkau dan mudah ditemukan "
        "di pasar tradisional, seperti: tahu, tempe, telur, bayam, kangkung, daun kelor, "
        "hati ayam, ikan lele, ikan teri, nasi merah, jagung, singkong, ubi jalar, pepaya, "
        "pisang, jeruk lokal, kacang hijau, kedelai, wortel, labu kuning, tomat, daun "
        "singkong, terong, sawi hijau, tauge, brokoli lokal, dan sejenisnya.\n"
        "- DILARANG KERAS merekomendasikan bahan impor mahal seperti: salmon, tuna segar "
        "premium, blueberry, raspberry, strawberry impor, quinoa, oatmeal, asparagus, "
        "avocado impor, chia seed, flaxseed, acai berry, kale impor, edamame frozen impor, "
        "Greek yogurt, granola, almond butter, macadamia, atau bahan mahal sejenis.\n"
        "- Seluruh bahan harus bisa dibeli dengan total Rp 5.000 - Rp 25.000.\n\n"
        "### 2. FILTER ALERGI KETAT\n"
        f"- Pengguna ini memiliki ALERGI terhadap: **{alergi}**.\n"
    )

    if alergi.lower() != "tidak ada":
        daftar_alergi = [a.strip() for a in alergi.split(",")]
        instruksi += (
            "- DILARANG KERAS merekomendasikan menu yang mengandung bahan-bahan berikut "
            "beserta SELURUH TURUNAN dan OLAHAN-nya:\n"
        )
        for item in daftar_alergi:
            instruksi += f"  * {item} (termasuk semua produk olahan yang mengandung {item})\n"
        instruksi += (
            "- Jika tidak ada menu yang aman dari alergi, jelaskan dengan sopan dan "
            "sarankan pengguna untuk berkonsultasi ke dokter.\n"
        )
    else:
        instruksi += "- Pengguna tidak memiliki alergi. Tidak ada batasan bahan.\n"

    instruksi += (
        "\n### 3. FORMAT JAWABAN (WAJIB DIIKUTI PERSIS)\n"
        "Jawab HANYA dalam format berikut, tanpa tambahan teks lain di luar format ini:\n\n"
        "🍽️ *REKOMENDASI MENU SEHAT*\n\n"
        "Menu: [Nama Masakan Indonesia yang Spesifik]\n"
        "Bahan: [Sebutkan semua bahan utama, pisahkan dengan koma]\n"
        "Alasan Medis: [Jelaskan singkat kenapa menu ini cocok untuk keluhan pengguna, "
        "sebutkan kandungan gizi yang relevan]\n"
        "Estimasi Harga: [Perkiraan total harga bahan dalam Rupiah, misal: Rp 10.000 - Rp 15.000]\n\n"
        "💡 *Tips Tambahan:* [Satu kalimat tips kesehatan singkat yang relevan]\n\n"
        "### 4. GAYA BAHASA\n"
        "- Gunakan bahasa Indonesia yang ramah, hangat, dan mudah dipahami.\n"
        "- Jangan gunakan istilah medis yang terlalu teknis.\n"
        "- Berikan semangat dan motivasi kepada pengguna.\n"
    )

    return instruksi


# ══════════════════════════════════════════════
# HANDLER — /start
# ══════════════════════════════════════════════
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menyapa pengguna dan memberikan panduan penggunaan bot."""
    user = update.effective_user
    get_or_create_user(user.id)

    pesan = (
        f"🌿 *Halo, {user.first_name}!* Selamat datang di *Bot Asisten Nutrisi Sehat & Murah* 🇮🇩\n\n"
        "Saya adalah asisten AI yang siap membantu kamu mendapatkan rekomendasi menu "
        "makanan sehat, murah, dan mudah didapat di pasar tradisional Indonesia! 🏪\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *CARA MENGGUNAKAN BOT INI:*\n\n"
        "1️⃣ *Daftarkan Alergi* (opsional tapi penting!)\n"
        "   Ketik: `/alergi telur, udang, kacang`\n"
        "   _(pisahkan dengan koma jika lebih dari satu)_\n\n"
        "   Jika tidak punya alergi, ketik:\n"
        "   `/alergi tidak ada`\n\n"
        "2️⃣ *Konsultasi Kesehatan*\n"
        "   Cukup ketik keluhan kesehatanmu, contoh:\n"
        "   • _\"Saya lemas karena anemia\"_\n"
        "   • _\"Anak saya susah makan dan kurus\"_\n"
        "   • _\"Saya butuh menu diet murah\"_\n"
        "   • _\"Ibu hamil butuh asupan zat besi\"_\n\n"
        "3️⃣ *Terima Rekomendasi + Pengingat*\n"
        "   AI akan memberikan menu sehat lokal yang murah,\n"
        "   lalu mengirim pengingat otomatis agar kamu\n"
        "   tidak lupa makan sehat! ⏰\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 Data alergimu tersimpan aman dan bisa diubah kapan saja.\n\n"
        "Yuk, mulai konsultasi sekarang! 💪✨"
    )

    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# HANDLER — /alergi
# ══════════════════════════════════════════════
async def alergi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menyimpan atau mereset data alergi pengguna."""
    user = update.effective_user
    get_or_create_user(user.id)

    # Ambil argumen setelah /alergi
    if not context.args:
        await update.message.reply_text(
            "⚠️ *Format salah!*\n\n"
            "Cara penggunaan:\n"
            "• `/alergi telur, udang, kacang`\n"
            "• `/alergi tidak ada` _(untuk reset)_\n\n"
            "Pisahkan bahan alergi dengan tanda koma.",
            parse_mode="Markdown",
        )
        return

    teks_alergi = " ".join(context.args)

    # Cek apakah pengguna ingin mereset alergi
    if teks_alergi.lower().strip() in ("tidak ada", "tidak", "none", "reset", "hapus"):
        update_alergi(user.id, "Tidak ada")
        await update.message.reply_text(
            "✅ *Data alergi berhasil direset!*\n\n"
            "Sekarang kamu tidak memiliki catatan alergi.\n"
            "Kamu bisa mendaftarkan ulang kapan saja dengan:\n"
            "`/alergi [bahan1, bahan2, ...]`",
            parse_mode="Markdown",
        )
        return

    # Bersihkan dan simpan alergi
    alergi_bersih = bersihkan_alergi(teks_alergi)

    if not alergi_bersih:
        await update.message.reply_text(
            "⚠️ Input alergi tidak valid. Silakan coba lagi.",
            parse_mode="Markdown",
        )
        return

    update_alergi(user.id, alergi_bersih)

    # Tampilkan daftar alergi sebagai list
    daftar = alergi_bersih.split(", ")
    daftar_format = "\n".join([f"  🚫 {item.capitalize()}" for item in daftar])

    await update.message.reply_text(
        f"✅ *Data alergi berhasil disimpan!*\n\n"
        f"📝 Daftar alergi kamu:\n{daftar_format}\n\n"
        f"Bot akan memastikan semua rekomendasi menu\n"
        f"*BEBAS* dari bahan-bahan di atas.\n\n"
        f"Sekarang, ceritakan keluhan kesehatanmu! 😊",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
# CALLBACK — Pengingat Otomatis (Job Queue)
# ══════════════════════════════════════════════
async def kirim_pengingat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback yang dipanggil oleh job_queue untuk mengirim pengingat."""
    job = context.job
    chat_id = job.chat_id
    nama_menu = job.data  # nama menu disimpan di job.data

    pesan_pengingat = (
        "🔔 *Waktunya Makan Sehat!*\n\n"
        f"Jangan lupa mengonsumsi menu rekomendasi AI-mu hari ini:\n"
        f"🍽️ *{nama_menu}*\n\n"
        "Tetap semangat dan jaga kesehatan ya! 💪🌿\n\n"
        "_Pengingat ini dikirim otomatis oleh Bot Asisten Nutrisi._"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=pesan_pengingat,
        parse_mode="Markdown",
    )
    logger.info("Pengingat terkirim ke user %s untuk menu: %s", chat_id, nama_menu)


# ══════════════════════════════════════════════
# HANDLER — Pesan Teks Biasa (Konsultasi)
# ══════════════════════════════════════════════
async def konsultasi_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menerima keluhan kesehatan dan meminta rekomendasi dari Gemini AI."""
    user = update.effective_user
    user_data = get_or_create_user(user.id)
    keluhan = update.message.text.strip()

    if not keluhan:
        await update.message.reply_text("Silakan ketik keluhan kesehatanmu. 😊")
        return

    # Kirim indikator bahwa bot sedang memproses
    pesan_tunggu = await update.message.reply_text(
        "⏳ Sedang menganalisis keluhanmu dan menyiapkan rekomendasi menu sehat...\n"
        "Mohon tunggu sebentar ya! 🔍"
    )

    try:
        # Ambil data alergi terbaru dari database
        alergi_pengguna = user_data["alergi"]

        # Bangun system instruction dinamis
        system_instruction = bangun_system_instruction(alergi_pengguna)

        # Kirim ke Gemini AI
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Keluhan kesehatan saya: {keluhan}",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )

        # Ambil teks respons
        jawaban_ai = response.text

        if not jawaban_ai:
            await pesan_tunggu.edit_text(
                "😔 Maaf, AI tidak dapat memberikan rekomendasi saat ini.\n"
                "Silakan coba lagi nanti atau ubah keluhan kamu."
            )
            return

        # Ekstrak nama menu dari respons
        nama_menu = ekstrak_nama_menu(jawaban_ai)

        # Simpan menu ke database
        update_menu(user.id, nama_menu)

        # Kirim respons AI ke pengguna
        info_alergi = (
            f"\n\n🔒 _Filter alergi aktif: {alergi_pengguna}_"
            if alergi_pengguna.lower() != "tidak ada"
            else ""
        )

        await pesan_tunggu.edit_text(
            f"{jawaban_ai}{info_alergi}",
            parse_mode="Markdown",
        )

        # ── Jadwalkan Pengingat Otomatis (10 detik) ──
        context.job_queue.run_once(
            callback=kirim_pengingat,
            when=10,  # 10 detik setelah konsultasi
            chat_id=update.effective_chat.id,
            name=f"reminder_{user.id}",
            data=nama_menu,
        )

        logger.info(
            "Pengingat dijadwalkan untuk user %s dalam 10 detik. Menu: %s",
            user.id,
            nama_menu,
        )

    except Exception as e:
        logger.error("Error saat konsultasi Gemini: %s", str(e))
        await pesan_tunggu.edit_text(
            "❌ *Terjadi kesalahan saat memproses permintaanmu.*\n\n"
            f"Detail error: `{str(e)}`\n\n"
            "Silakan coba lagi dalam beberapa saat.",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# HANDLER — Error Global
# ══════════════════════════════════════════════
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani error yang tidak tertangkap oleh handler lain."""
    logger.error("Update %s menyebabkan error: %s", update, context.error)


# ══════════════════════════════════════════════
# MAIN — Jalankan Bot
# ══════════════════════════════════════════════
def main() -> None:
    """Fungsi utama untuk menjalankan bot Telegram."""
    logger.info("Menginisialisasi Bot Asisten Nutrisi Sehat & Murah...")

    # Inisialisasi database
    init_db()

    # Bangun aplikasi bot dengan job_queue aktif
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Daftarkan handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("alergi", alergi_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, konsultasi_handler)
    )

    # Daftarkan error handler
    application.add_error_handler(error_handler)

    # Jalankan bot dengan polling
    logger.info("Bot berjalan! Tekan Ctrl+C untuk menghentikan.")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()

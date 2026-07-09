"""
Bot Telegram: Asisten Nutrisi Sehat & Murah ala Indonesia
=========================================================
Fitur:
  - Menu Navigasi berbasis Tombol (Reply Keyboard / Inline Keyboard)
  - Registrasi alergi TANPA slash & dengan Tombol
  - Konsultasi kesehatan via pesan teks biasa
  - Rekomendasi menu lokal murah dari Gemini AI dengan filter alergi ketat
  - Pengingat otomatis 10 detik setelah konsultasi (simulasi reminder)
  - Database SQLite lengkap (profil user, alergi, riwayat konsultasi)
  - Fitur: Profil, Riwayat, Bantuan, Reset Data, Panduan Alergi
"""

import logging
import sqlite3
import os
import re
from datetime import datetime
from pathlib import Path

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
# Regex untuk deteksi kata "alergi" / "alrgi" / "allergi" di awal pesan
# ──────────────────────────────────────────────
POLA_ALERGI = re.compile(
    r"^(?:alergi|alrgi|allergi|alerji|alergy|allergy)\s+(.+)",
    re.IGNORECASE,
)

# ──────────────────────────────────────────────
# SQLite — Inisialisasi Database
# ──────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "bot_data.db"


def init_db() -> None:
    """Membuat tabel users dan riwayat jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tabel profil pengguna
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            nama        TEXT    DEFAULT '',
            alergi      TEXT    DEFAULT 'Tidak ada',
            menu        TEXT    DEFAULT '',
            reminder    INTEGER DEFAULT 0,
            bergabung   TEXT    DEFAULT ''
        )
        """
    )

    # Tabel riwayat konsultasi
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS riwayat (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            keluhan     TEXT    NOT NULL,
            menu        TEXT    NOT NULL,
            jawaban_ai  TEXT    NOT NULL,
            waktu       TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """
    )

    conn.commit()
    conn.close()
    logger.info("Database SQLite siap digunakan (tabel users + riwayat).")


def get_or_create_user(user_id: int, nama: str = "") -> dict:
    """Mengambil data user; buat baris baru jika belum ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, nama, alergi, menu, reminder, bergabung FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        waktu_gabung = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute(
            "INSERT INTO users (user_id, nama, bergabung) VALUES (?, ?, ?)",
            (user_id, nama, waktu_gabung),
        )
        conn.commit()
        row = (user_id, nama, "Tidak ada", "", 0, waktu_gabung)
    elif nama and row[1] != nama:
        # Update nama jika berubah
        cursor.execute("UPDATE users SET nama = ? WHERE user_id = ?", (nama, user_id))
        conn.commit()
        row = (row[0], nama, row[2], row[3], row[4], row[5])
    conn.close()
    return {
        "user_id": row[0],
        "nama": row[1],
        "alergi": row[2],
        "menu": row[3],
        "reminder": row[4],
        "bergabung": row[5],
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
    cursor.execute(
        "UPDATE users SET menu = ?, reminder = 1 WHERE user_id = ?", (menu, user_id)
    )
    conn.commit()
    conn.close()


def simpan_riwayat(user_id: int, keluhan: str, menu: str, jawaban_ai: str) -> None:
    """Menyimpan riwayat konsultasi ke database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO riwayat (user_id, keluhan, menu, jawaban_ai, waktu) VALUES (?, ?, ?, ?, ?)",
        (user_id, keluhan, menu, jawaban_ai, waktu),
    )
    conn.commit()
    conn.close()


def ambil_riwayat(user_id: int, limit: int = 10) -> list:
    """Mengambil riwayat konsultasi terakhir pengguna."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT keluhan, menu, waktu FROM riwayat WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def hitung_total_konsultasi(user_id: int) -> int:
    """Menghitung total konsultasi pengguna."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM riwayat WHERE user_id = ?", (user_id,))
    total = cursor.fetchone()[0]
    conn.close()
    return total


def reset_user_data(user_id: int) -> None:
    """Menghapus semua data pengguna dari database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM riwayat WHERE user_id = ?", (user_id,))
    cursor.execute(
        "UPDATE users SET alergi = 'Tidak ada', menu = '', reminder = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
# Helper — Bersihkan teks alergi
# ──────────────────────────────────────────────
def bersihkan_alergi(teks: str) -> str:
    """Ubah ke huruf kecil, hapus spasi berlebih, rapikan koma."""
    teks = teks.lower().strip()
    items = [item.strip() for item in teks.split(",") if item.strip()]
    return ", ".join(items)


# ──────────────────────────────────────────────
# Helper — Ekstrak nama menu dari respons Gemini
# ──────────────────────────────────────────────
def ekstrak_nama_menu(respons: str) -> str:
    """Mengambil nama menu secara cerdas dari respons Gemini."""
    # Cari pola "Menu: Nama Menu" atau "* Menu: Nama Menu"
    match = re.search(r"(?:Menu|Rekomendasi Menu)\s*:\s*([^\n]+)", respons, re.IGNORECASE)
    if match:
        return match.group(1).replace("*", "").strip()
    
    # Fallback: ambil baris pertama yang mengandung masakan
    for line in respons.split("\n"):
        if any(keyword in line.lower() for keyword in ["tumis", "nasi", "sup", "bubur", "sayur", "rebus", "ikan", "ayam", "tahu", "tempe"]):
            return line.replace("*", "").strip()
            
    return "Menu Sehat & Nutrisi Lokal"


# ──────────────────────────────────────────────
# Bangun System Instruction dinamis untuk Gemini
# ──────────────────────────────────────────────
def bangun_system_instruction(alergi: str) -> str:
    """Membuat system instruction Gemini yang fleksibel tapi tetap menyaring alergi."""
    instruksi = (
        "Kamu adalah seorang Dokter, Spesialis Nutrisi, dan Ahli Gizi Ramah Indonesia yang sangat berpengalaman.\n"
        "Tugasmu adalah memberikan analisis keluhan kesehatan pengguna dan memberikan rekomendasi menu sehat "
        "lokal Indonesia beserta tips gaya hidup/pola tidur medis yang sangat lengkap dan solutif. Jangan memotong penjelasan penting!\n\n"
        "## ATURAN MUTLAK YANG WAJIB DIPATUHI:\n\n"
        "### 1. RENCANA MENU HARUS MURAH & LOKAL INDONESIA\n"
        "- Gunakan bahan makanan lokal yang terjangkau di pasar tradisional (tahu, tempe, telur, bayam, kangkung, daun kelor, hati ayam, pisang, pepaya, ubi, singkong, kacang hijau, lele, ikan teri, dll).\n"
        "- DILARANG keras menyarankan bahan impor mahal seperti salmon, tuna segar premium, blueberry, quinoa, oatmeal, asparagus, chia seed, dll.\n"
        "- Estimasi total harga bahan harus ramah kantong (Rp 5.000 - Rp 25.000).\n\n"
        "### 2. FILTER ALERGI KETAT\n"
        f"- Pengguna memiliki ALERGI terhadap: **{alergi}**.\n"
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
    """Menyapa pengguna dan menampilkan menu keyboard utama."""
    user = update.effective_user
    get_or_create_user(user.id, user.first_name)

    pesan = (
        f"🌿 *Halo, {user.first_name}!* Selamat datang di *Bot Asisten Nutrisi Sehat & Murah* 🇮🇩\n\n"
        "Saya adalah asisten AI yang siap membantu kamu mendapatkan rekomendasi menu "
        "makanan sehat, murah, dan bebas alergi. Kamu bisa menggunakan tombol di bawah untuk menavigasi bot ini!\n\n"
        "👇 *Silakan gunakan tombol menu di bawah untuk mulai!*"
    )

    await update.message.reply_text(
        pesan,
        parse_mode="Markdown",
        reply_markup=dapatkan_keyboard_utama(),
    )


# ══════════════════════════════════════════════
# HANDLER — Kelola Alergi (Inline Keyboard)
# ══════════════════════════════════════════════
async def kelola_alergi_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan pilihan kelola alergi dengan tombol inline."""
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.first_name)

    keyboard = [
        [
            InlineKeyboardButton("🥚 Telur", callback_data="set_alergi_telur"),
            InlineKeyboardButton("🦐 Udang", callback_data="set_alergi_udang"),
        ],
        [
            InlineKeyboardButton("🥜 Kacang", callback_data="set_alergi_kacang"),
            InlineKeyboardButton("🥛 Susu", callback_data="set_alergi_susu"),
        ],
        [
            InlineKeyboardButton("🐟 Ikan Laut", callback_data="set_alergi_ikan"),
            InlineKeyboardButton("🌾 Gandum/Gluten", callback_data="set_alergi_gandum"),
        ],
        [
            InlineKeyboardButton("✅ Hapus Semua Alergi", callback_data="reset_alergi"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        "🥗 *KELOLA ALERGI KAMU*\n\n"
        f"Status Alergi Saat Ini: *{user_data['alergi']}*\n\n"
        "Klik tombol di bawah untuk menambah alergi secara instan,\n"
        "atau ketik manual dengan format: `alergi telur, kepiting, dll`."
    )

    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


# ══════════════════════════════════════════════
# CALLBACK HANDLER — Proses Klik Tombol Alergi
# ══════════════════════════════════════════════
async def callback_alergi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Memproses callback query dari tombol inline alergi."""
    query = update.callback_query
    user = query.from_user
    user_data = get_or_create_user(user.id, user.first_name)

    await query.answer()

    action = query.data

    if action == "reset_alergi":
        update_alergi(user.id, "Tidak ada")
        await query.edit_message_text(
            "✅ *Semua alergi berhasil dihapus!*\n\n"
            "Sekarang kamu bebas mengonsumsi semua jenis makanan.",
            parse_mode="Markdown",
        )
    elif action.startswith("set_alergi_"):
        bahan = action.replace("set_alergi_", "")
        alergi_sekarang = user_data["alergi"]

        if alergi_sekarang.lower() == "tidak ada":
            alergi_baru = bahan
        else:
            daftar_sekarang = [x.strip() for x in alergi_sekarang.split(",")]
            if bahan not in daftar_sekarang:
                daftar_sekarang.append(bahan)
            alergi_baru = ", ".join(daftar_sekarang)

        update_alergi(user.id, alergi_baru)
        await query.edit_message_text(
            f"✅ *Alergi '{bahan.capitalize()}' berhasil ditambahkan!*\n\n"
            f"Daftar alergi aktif: *{alergi_baru}*",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# HANDLER — Profil
# ══════════════════════════════════════════════
async def profil_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan profil pengguna."""
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.first_name)
    total_konsultasi = hitung_total_konsultasi(user.id)

    # Format daftar alergi
    alergi = user_data["alergi"]
    if alergi.lower() != "tidak ada":
        daftar = alergi.split(", ")
        alergi_display = "\n".join([f"  🚫 {item.capitalize()}" for item in daftar])
    else:
        alergi_display = "  ✅ Tidak ada alergi tercatat"

    menu_terakhir = user_data["menu"] if user_data["menu"] else "Belum ada konsultasi"

    # Tombol hapus riwayat & profil
    keyboard = [[InlineKeyboardButton("🗑️ Hapus Riwayat & Data", callback_data="confirm_reset")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        "👤 *PROFIL PENGGUNA*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ Nama: *{user_data['nama'] or user.first_name}*\n"
        f"🆔 User ID: `{user.id}`\n"
        f"📅 Bergabung: {user_data['bergabung']}\n"
        f"📊 Total Konsultasi: *{total_konsultasi} kali*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧬 *Daftar Alergi:*\n{alergi_display}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🍽️ *Menu Terakhir:*\n  {menu_terakhir}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(pesan, parse_mode="Markdown", reply_markup=reply_markup)


# ══════════════════════════════════════════════
# CALLBACK HANDLER — Reset Data via Profil
# ══════════════════════════════════════════════
async def callback_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Konfirmasi dan lakukan reset data pengguna."""
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if query.data == "confirm_reset":
        reset_user_data(user.id)
        await query.edit_message_text(
            "🗑️ *Semua data profil & riwayat konsultasi kamu berhasil dihapus bersih!*",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# HANDLER — Riwayat
# ══════════════════════════════════════════════
async def riwayat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan riwayat konsultasi."""
    user = update.effective_user
    rows = ambil_riwayat(user.id, limit=5)

    if not rows:
        await update.message.reply_text(
            "📭 *Belum ada riwayat konsultasi.*\n\n"
            "Silakan ketik langsung keluhan kesehatanmu untuk memulai!",
            parse_mode="Markdown",
        )
        return

    pesan = "📋 *5 KONSULTASI TERAKHIR KAMU*\n\n"
    for i, (keluhan, menu, waktu) in enumerate(rows, 1):
        keluhan_singkat = keluhan[:50] + "..." if len(keluhan) > 50 else keluhan
        pesan += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*{i}.* 🕐 {waktu}\n"
            f"   💬 Keluhan: _{keluhan_singkat}_\n"
            f"   🍽️ Menu: *{menu}*\n"
        )

    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# HANDLER — Bantuan & Tips
# ══════════════════════════════════════════════
async def bantuan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan panduan penggunaan dan tips kesehatan."""
    pesan = (
        "📖 *PANDUAN & TIPS KESEHATAN*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🥗 *CARA KONSULTASI:*\n"
        "Cukup ketik langsung keluhan kesehatanmu di chat ini. Contoh:\n"
        "• _'Badan saya lemas dan kurang darah'_\n"
        "• _'Rekomendasi makanan untuk penderita maag'_\n"
        "• _'Menu sehat murah peningkat nafsu makan anak'_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🧬 *CARA SET ALERGI:*\n"
        "1. Klik tombol *🥗 Kelola Alergi* di bawah.\n"
        "2. Pilih alergi instan dengan tombol yang tersedia,\n"
        "3. Atau ketik manual di chat: `alergi telur, udang, susu`.\n"
        "4. Reset alergi kapan saja dengan tombol *Hapus Semua Alergi*.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tips Makan Sehat & Hemat:*\n"
        "• Selalu utamakan bahan berprotein lokal seperti Tempe dan Tahu yang kaya protein nabati.\n"
        "• Konsumsi sayur daun kelor atau bayam sebagai sumber zat besi alami termurah.\n"
        "• Hindari makanan olahan instan berlebih agar tubuh tetap prima!"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown")


# ══════════════════════════════════════════════
# CALLBACK — Pengingat Otomatis (Job Queue)
# ══════════════════════════════════════════════
async def kirim_pengingat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim pesan pengingat setelah 10 detik."""
    job = context.job
    chat_id = job.chat_id
    nama_menu = job.data

    pesan_pengingat = (
        "🔔 *Waktunya Makan Sehat!*\n\n"
        f"Jangan lupa mengonsumsi menu rekomendasi AI-mu hari ini:\n"
        f"🍽️ *{nama_menu}*\n\n"
        "Tetap semangat dan jaga kesehatan ya! 💪🌿"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=pesan_pengingat,
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════
# HANDLER — Pesan Teks Utama (Menangani Teks Biasa/Tombol Menu/Alergi)
# ══════════════════════════════════════════════
async def pesan_teks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menerima input dari pengguna, baik klik tombol keyboard maupun ketik manual."""
    user = update.effective_user
    teks = update.message.text.strip()

    if not teks:
        return

    # 1. Hubungkan tombol menu keyboard utama ke fungsi masing-masing
    if teks == "🥗 Kelola Alergi":
        await kelola_alergi_menu(update, context)
        return
    elif teks == "👤 Profil Saya":
        await profil_menu(update, context)
        return
    elif teks == "📋 Riwayat Menu":
        await riwayat_menu(update, context)
        return
    elif teks == "📖 Bantuan & Tips":
        await bantuan_menu(update, context)
        return

    # 2. Cek apakah pengguna mengetik format pendaftaran alergi manual
    cocok = POLA_ALERGI.match(teks)
    if cocok:
        teks_alergi = cocok.group(1).strip()
        get_or_create_user(user.id, user.first_name)

        if teks_alergi.lower() in ("tidak ada", "tidak", "none", "reset", "hapus", "kosong", "ga ada"):
            update_alergi(user.id, "Tidak ada")
            await update.message.reply_text("✅ *Data alergi berhasil direset menjadi 'Tidak ada'!*", parse_mode="Markdown")
            return

        alergi_bersih = bersihkan_alergi(teks_alergi)
        update_alergi(user.id, alergi_bersih)
        await update.message.reply_text(
            f"✅ *Alergi manual berhasil disimpan!*\n\nDaftar alergi aktif: *{alergi_bersih}*",
            parse_mode="Markdown"
        )
        return

    # 3. Selain itu, proses sebagai konsultasi kesehatan
    await proses_konsultasi(update, context, user, teks)


# ──────────────────────────────────────────────
# Sub-handler: Proses Konsultasi Kesehatan ke Gemini
# ──────────────────────────────────────────────
async def proses_konsultasi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    keluhan: str,
) -> None:
    """Mengirim keluhan ke Gemini AI dengan menyertakan memori chat terakhir dari SQLite."""
    user_data = get_or_create_user(user.id, user.first_name)

    pesan_tunggu = await update.message.reply_text(
        "⏳ Sedang menganalisis keluhanmu dan menyiapkan rekomendasi menu sehat...\n"
        "Mohon tunggu sebentar ya! 🔍"
    )

    try:
        alergi_pengguna = user_data["alergi"]
        system_instruction = bangun_system_instruction(alergi_pengguna)

        # Ambil riwayat percakapan terakhir (maksimal 3 riwayat terakhir) untuk memori konteks AI
        riwayat_terakhir = ambil_riwayat(user.id, limit=3)
        konteks_percakapan = ""
        
        if riwayat_terakhir:
            konteks_percakapan = "Berikut adalah riwayat konsultasi terakhir dari pengguna ini untuk menjaga kesinambungan percakapan:\n"
            # Urutkan dari yang terlama ke terbaru (riwayat diambil DESC, jadi kita balik)
            for r_keluhan, r_menu, r_waktu in reversed(riwayat_terakhir):
                konteks_percakapan += f"- Waktu: {r_waktu} | Keluhan: '{r_keluhan}' | Menu Direkomendasikan: '{r_menu}'\n"
            konteks_percakapan += "\nGunakan informasi di atas untuk melanjutkan konsultasi jika keluhan baru ini berhubungan dengan keluhan sebelumnya. Jangan rekomendasikan menu yang sama persis jika keluhannya mirip, berikan variasi menu baru!\n\n"

        # Gabungkan konteks riwayat dengan keluhan saat ini
        prompt_final = f"{konteks_percakapan}Keluhan kesehatan baru saya saat ini: {keluhan}"

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_final,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2, # Sedikit dinaikkan agar variatif tapi tetap patuh
                max_output_tokens=1024,
            ),
        )

        jawaban_ai = response.text

        if not jawaban_ai:
            await pesan_tunggu.edit_text("😔 Maaf, AI tidak dapat memberikan rekomendasi saat ini. Silakan coba lagi.")
            return

        nama_menu = ekstrak_nama_menu(jawaban_ai)

        # Simpan ke database (riwayat & menu terakhir)
        update_menu(user.id, nama_menu)
        simpan_riwayat(user.id, keluhan, nama_menu, jawaban_ai)

        info_alergi = (
            f"\n\n🔒 _Filter alergi aktif: {alergi_pengguna}_"
            if alergi_pengguna.lower() != "tidak ada"
            else ""
        )

        await pesan_tunggu.edit_text(f"{jawaban_ai}{info_alergi}", parse_mode="Markdown")

        # Hapus pengingat lama jika ada, lalu jadwalkan yang baru (10 detik)
        jobs_lama = context.job_queue.get_jobs_by_name(f"reminder_{user.id}")
        for job in jobs_lama:
            job.schedule_removal()

        context.job_queue.run_once(
            callback=kirim_pengingat,
            when=10,
            chat_id=update.effective_chat.id,
            name=f"reminder_{user.id}",
            data=nama_menu,
        )

    except Exception as e:
        logger.error("Error Gemini: %s", str(e))
        await pesan_tunggu.edit_text(
            f"❌ *Terjadi kesalahan.*\n\nDetail: `{str(e)}`",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════
# MAIN — Jalankan Bot
# ══════════════════════════════════════════════
def main() -> None:
    """Fungsi utama untuk menjalankan bot Telegram."""
    init_db()

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_alergi, pattern="^(set_alergi_|reset_alergi)"))
    application.add_handler(CallbackQueryHandler(callback_reset, pattern="^confirm_reset$"))
    
    # Menangani semua teks (baik klik tombol keyboard utama maupun input bebas)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pesan_teks_handler))

    logger.info("Bot berjalan dengan fitur tombol navigasi instan!")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

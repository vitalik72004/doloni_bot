import os
import asyncio
import logging
import random
import string
from datetime import datetime

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage


# =========================
# ENV / CONFIG
# =========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPERATORS_GROUP_ID = int(os.getenv("OPERATORS_GROUP_ID", "0").strip() or "0")

ADMIN_IDS: set[int] = set()
_admin_raw = os.getenv("ADMIN_IDS", "").strip()
if _admin_raw:
    ADMIN_IDS = {int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()}

# WhatsApp numbers (digits only, no +)
WA1 = "393920725322"
WA2 = "393286058012"

DB_PATH = "doloni.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("doloni-bot")


# =========================
# i18n
# =========================
T = {
    "it": {
        "choose_lang": "🌐 Scegli la lingua:",
        "welcome_registered": "👋 Benvenuto/a in <b>Doloni Documenti</b>.\nSeleziona un servizio ⬇️",
        "welcome_need_phone": "👋 Benvenuto/a in <b>Doloni Documenti</b>\nPer iniziare, condividi il tuo numero di telefono.",
        "btn_share_phone": "📱 Condividi numero",
        "use_share_phone": "Per favore usa il pulsante <b>Condividi numero</b>.",
        "enter_surname": "Grazie! Inserisci il tuo <b>Cognome</b>.",
        "enter_name": "Ora inserisci il tuo <b>Nome</b>.",
        "done": "✅ Perfetto, <b>{name}</b>!\nSeleziona il servizio di tuo interesse ⬇️",
        "menu": "Menu:",
        "select_service": "Seleziona un servizio ⬇️",
        "service_title": "<b>{service}</b>\nSeleziona cosa vuoi fare:",
        "docs_btn": "📄 Documenti necessari",
        "price_btn": "💶 Prezzo indicativo",
        "wa_btn": "💬 Continua su WhatsApp",
        "tg_btn": "💬 Operatore su Telegram",
        "back_btn": "⬅️ Torna ai servizi",
        "choose_operator_where": "Vuoi continuare su WhatsApp oppure parlare qui su Telegram?",
        "wa_recommended": "📲 WhatsApp (consigliato)",
        "tg_here": "💬 Telegram (qui)",
        "back": "⬅️ Indietro",
        "write_to_operator": "💬 Scrivi qui il tuo messaggio per l’operatore.\nTi risponderemo qui su Telegram.",
        "write_to_operator_for": "💬 Scrivi il tuo messaggio per <b>{service}</b>.\nTi risponderemo qui su Telegram.",
        "request_sent": "✅ Richiesta inviata a <b>Doloni Documenti</b>.\n<b>ID:</b> {ticket}\nTi risponderemo qui.",
        "request_sent_short": "✅ Richiesta inviata.\n<b>ID:</b> {ticket}",
        "ticket_closed": "✅ La conversazione è stata chiusa.\nSe hai bisogno, scrivi di nuovo qui.",
        "open_whatsapp": "📲 Apri WhatsApp: {link}",
        "open_whatsapp_service": "📲 WhatsApp ({service}): {link}",
        "admin_denied": "Accesso negato.",
        "admin_title": "🛠️ <b>Doloni Admin</b>",
        "admin_new": "📥 Nuovi",
        "admin_progress": "⏳ In lavorazione",
        "admin_closed": "✅ Chiusi",
        "admin_search": "🔎 Cerca (scrivi ID)",
        "admin_search_ask": "Scrivi l’ID del ticket (es: DD-2026-123456).",
        "ticket_not_found": "Ticket non trovato.",
        "tickets_none": "Nessun ticket in questa lista.",
        "tickets_list": "📋 Tickets:\n{lines}",
        "ticket_found": "✅ Trovato: <b>{id}</b>\nServizio: {service}\nStatus: {status}\nAssegnato: {assigned}",
        "only_operators": "Solo operatori.",
        "already_taken": "Già preso da un altro operatore.",
        "taken_ok": "Preso in carico ✅",
        "assigned_other": "Ticket assegnato a un altro operatore.",
        "active_chat_on": "✅ Chat attiva: <b>{ticket}</b>\nOra puoi scrivere qui in privato: ogni messaggio verrà inviato al cliente.\nPer uscire: /stop",
        "active_chat_off": "⛔️ Chat disattivata (era: <b>{ticket}</b>).",
        "no_active_chat": "Non hai una chat attiva.",
        "sent_ok": "✅ Inviato.",
        "hint_admin": "🛠️ Sei in modalità amministratore.\nApri una chat: vai nella chat operatori e premi ✉️ Rispondi su un ticket.\nPoi scrivi qui in privato.\nMenu: /admin\nUscire: /stop",
        "talk_to_operator": "💬 Parlare con un operatore",
        "ticket_new_prefix": "🆕",
        "ticket_msg_prefix": "📩",
        "ticket_text_new": "🆕 <b>Ticket {ticket}</b>\nCliente: {name} {surname}\nTel: +{phone}\nServizio: {service}\nMessaggio: “{msg}”",
        "ticket_text_msg": "📩 <b>Ticket {ticket}</b> (messaggio cliente)\n{name} {surname} | +{phone}\n“{msg}”",
        "claim_btn": "✅ Prendi in carico",
        "reply_btn": "✉️ Rispondi",
        "close_btn": "🔒 Chiudi",
        "docs_title": "<b>{service}</b> — Documenti necessari:\n{txt}",
        "price_title": "<b>{service}</b> — Prezzo indicativo:\n{txt}",
        "lang_set": "✅ Lingua impostata.",
    },
    "uk": {
        "choose_lang": "🌐 Оберіть мову:",
        "welcome_registered": "👋 Вітаємо у <b>Doloni Documenti</b>.\nОберіть послугу ⬇️",
        "welcome_need_phone": "👋 Вітаємо у <b>Doloni Documenti</b>\nЩоб почати, поділіться номером телефону.",
        "btn_share_phone": "📱 Поділитися номером",
        "use_share_phone": "Будь ласка, скористайтеся кнопкою <b>Поділитися номером</b>.",
        "enter_surname": "Дякуємо! Введіть ваше <b>Прізвище</b>.",
        "enter_name": "Тепер введіть ваше <b>Ім’я</b>.",
        "done": "✅ Чудово, <b>{name}</b>!\nОберіть послугу ⬇️",
        "menu": "Меню:",
        "select_service": "Оберіть послугу ⬇️",
        "service_title": "<b>{service}</b>\nОберіть дію:",
        "docs_btn": "📄 Потрібні документи",
        "price_btn": "💶 Орієнтовна вартість",
        "wa_btn": "💬 Продовжити у WhatsApp",
        "tg_btn": "💬 Оператор у Telegram",
        "back_btn": "⬅️ Назад до послуг",
        "choose_operator_where": "Бажаєте продовжити у WhatsApp чи поспілкуватися тут у Telegram?",
        "wa_recommended": "📲 WhatsApp (рекомендовано)",
        "tg_here": "💬 Telegram (тут)",
        "back": "⬅️ Назад",
        "write_to_operator": "💬 Напишіть тут повідомлення для оператора.\nМи відповімо вам тут у Telegram.",
        "write_to_operator_for": "💬 Напишіть повідомлення щодо <b>{service}</b>.\nМи відповімо вам тут у Telegram.",
        "request_sent": "✅ Запит надіслано до <b>Doloni Documenti</b>.\n<b>ID:</b> {ticket}\nМи відповімо вам тут.",
        "request_sent_short": "✅ Запит надіслано.\n<b>ID:</b> {ticket}",
        "ticket_closed": "✅ Діалог закрито.\nЯкщо буде потрібно — напишіть нам тут знову.",
        "open_whatsapp": "📲 Відкрити WhatsApp: {link}",
        "open_whatsapp_service": "📲 WhatsApp ({service}): {link}",
        "admin_denied": "Доступ заборонено.",
        "admin_title": "🛠️ <b>Doloni Admin</b>",
        "admin_new": "📥 Нові",
        "admin_progress": "⏳ В роботі",
        "admin_closed": "✅ Закриті",
        "admin_search": "🔎 Пошук (введіть ID)",
        "admin_search_ask": "Введіть ID тікету (наприклад: DD-2026-123456).",
        "ticket_not_found": "Тікет не знайдено.",
        "tickets_none": "У цьому списку немає тікетів.",
        "tickets_list": "📋 Тікети:\n{lines}",
        "ticket_found": "✅ Знайдено: <b>{id}</b>\nПослуга: {service}\nСтатус: {status}\nПризначено: {assigned}",
        "only_operators": "Тільки для операторів.",
        "already_taken": "Вже взято іншим оператором.",
        "taken_ok": "Взято в роботу ✅",
        "assigned_other": "Тікет призначено іншому оператору.",
        "active_chat_on": "✅ Активний чат: <b>{ticket}</b>\nТепер пишіть тут у приват — кожне повідомлення піде клієнту.\nВийти: /stop",
        "active_chat_off": "⛔️ Чат вимкнено (був: <b>{ticket}</b>).",
        "no_active_chat": "У вас немає активного чату.",
        "sent_ok": "✅ Надіслано.",
        "hint_admin": "🛠️ Ви в режимі адміністратора.\nВідкрийте чат: у групі операторів натисніть ✉️ Відповісти на тікеті.\nПотім пишіть тут у приват.\nМеню: /admin\nВийти: /stop",
        "talk_to_operator": "💬 Поспілкуватися з оператором",
        "ticket_new_prefix": "🆕",
        "ticket_msg_prefix": "📩",
        "ticket_text_new": "🆕 <b>Тікет {ticket}</b>\nКлієнт: {name} {surname}\nТел: +{phone}\nПослуга: {service}\nПовідомлення: “{msg}”",
        "ticket_text_msg": "📩 <b>Тікет {ticket}</b> (повідомлення клієнта)\n{name} {surname} | +{phone}\n“{msg}”",
        "claim_btn": "✅ Взяти",
        "reply_btn": "✉️ Відповісти",
        "close_btn": "🔒 Закрити",
        "docs_title": "<b>{service}</b> — Потрібні документи:\n{txt}",
        "price_title": "<b>{service}</b> — Орієнтовна вартість:\n{txt}",
        "lang_set": "✅ Мову встановлено.",
    }
}

def tr(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in T else "it"
    return T[lang][key].format(**kwargs)


# =========================
# CONTENT (docs/prices) in both langs
# service keys are stable; labels shown can be bilingual-friendly
# =========================
SERVICE_KEYS = [
    ("ISEE", "🧾 ISEE"),
    ("730", "📑 730"),
    ("Patente", "🚗 Conversione patente"),
    ("Permesso", "📄 Permesso di soggiorno"),
    ("AssegnoUnico", "👨‍👩‍👧 Assegno Unico"),
    ("ADI", "🤝 Assegno di Inclusione (ADI)"),
]

DOCS = {
    "it": {
        "ISEE": "- Documento d’identità\n- Codice fiscale\n- Contratto di affitto (se presente)\n- Saldo e giacenza media conti\n- CU / redditi (se presenti)\n- Stato di famiglia",
        "730": "- Documento e codice fiscale\n- CU\n- Spese mediche\n- Spese affitto / mutuo\n- Altre detrazioni",
        "Patente": "- Patente estera\n- Traduzzione della patente estera\n- Carta d’identità\n- Codice fiscale\n- Certificato anamnestico\n- Visita oculistica\n- Residenza in Italia",
        "Permesso": "- Passaporto\n- Permesso di soggiorno (se rinnovo)\n- Contratto di lavoro / reddito\n- Residenza o ospitalità",
        "AssegnoUnico": "- Documento e codice fiscale genitori\n- Codici fiscali figli\n- ISEE valido\n- IBAN",
        "ADI": "- Documento e codice fiscale\n- ISEE valido\n- Stato di famiglia\n- IBAN\n- Altri requisiti INPS",
    },
    "uk": {
        "ISEE": "- Carta d’identità або закордоний паспорт\n- Codice fiscale усіх членів сімї\n- Договір оренди (за наявності) та його реєстрація\n- Saldo e giacenza media (залишок/середній залишок) станом на 31.12.2024 усіх членів вашої сімї\n- Номерні знаки автомобіля або мотоцикла\n- CU / доходи (за наявності)\n- Stato di famiglia\n- У випадку якщо в когось із членів сімї є інвалідність потрібен також certificato telematico di invalidità",
        "730": "- Carta d’identità або закордоний паспорт\n- CU\n- Медичні витрати(Чеки)\n- Контракт оренди житла\n- Інші витрати для знижок\n- Codice fiscale дітей, якщо на вашому забезпеченні",
        "Patente": "- Водійські права\n- Переклад водійських прав\n- Carta d’identità\n- Codice fiscale\n- Медична довідка(візит вашого сімейного врача)\n- Довідка про візит окуліста, який спеціалізований для прав\n- Residenza в Італії",
        "Permesso": "- Закордоний паспорт\n- Permesso (якщо продовження)\n- Трудовий контракт \n- Residenza або ospitalità\n- Останні три Busta paga\n- 730 або CUd за минулий рік",
        "AssegnoUnico": "- Carta d’identità або закордоний паспорт батьків\n- Codice fiscale дітей\n- Дійсний ISEE\n- IBAN",
        "ADI": "- Carta d’identità або закордоний паспорт батьків\n- Дійсний ISEE\n- Stato di famiglia\n- IBAN\n- Інші вимоги INPS",
    }
}

PRICE = {
    "it": {
        "ISEE": "A partire da €, in base alla situazione familiare.",
        "730": "A partire da €60.",
        "Patente": "Il costo varia in base al caso. Ti daremo un preventivo preciso su WhatsApp.",
        "Permesso": "Il costo dipende dal tipo di permesso. Valutazione gratuita iniziale.",
        "AssegnoUnico": "A partire da €40.",
        "ADI": "Preventivo personalizzato in base al caso.",
    },
    "uk": {
        "ISEE": "Безкоштовне, але потребує запису до бази наших постійних клієнтів",
        "730": "Від €45.",
        "Patente": "Вартість конвертації коштує €500.",
        "Permesso": "Від €45, але потребує точно перегляду ситуації та документів.",
        "AssegnoUnico": "Вартість послуги €30.",
        "ADI": "Вартість послуги €30.",
    }
}


# =========================
# FSM (client)
# =========================
class RegStates(StatesGroup):
    wait_phone = State()
    wait_surname = State()
    wait_name = State()

class TicketStates(StatesGroup):
    wait_client_message = State()

class AdminSearch(StatesGroup):
    wait_ticket_id = State()


# =========================
# ACTIVE CHAT (operator -> ticket)
# operator_id -> ticket_id
# =========================
ACTIVE_TICKET: dict[int, str] = {}


# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_command_text(text: str | None) -> bool:
    return bool(text) and text.strip().startswith("/")

def choose_whatsapp_for_client(tg_id: int) -> str:
    return WA1 if (tg_id % 2 == 0) else WA2

def gen_ticket_id() -> str:
    year = datetime.utcnow().year
    num = "".join(random.choice(string.digits) for _ in range(6))
    return f"DD-{year}-{num}"

def wa_link(phone_digits: str, text: str) -> str:
    from urllib.parse import quote
    return f"https://wa.me/{phone_digits}?text={quote(text)}"


# =========================
# DB
# =========================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            tg_id INTEGER PRIMARY KEY,
            phone TEXT,
            surname TEXT,
            name TEXT,
            lang TEXT,
            created_at TEXT
        )
        """)
        # migration: add lang if missing
        try:
            await db.execute("ALTER TABLE clients ADD COLUMN lang TEXT")
        except Exception:
            pass

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            client_tg_id INTEGER,
            service TEXT,
            status TEXT, -- new, in_progress, closed
            assigned_operator_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT,
            from_role TEXT,  -- 'client' or 'operator'
            text TEXT,
            created_at TEXT
        )
        """)
        await db.commit()

async def get_client(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id, phone, surname, name, lang FROM clients WHERE tg_id=?", (tg_id,))
        return await cur.fetchone()

async def get_lang(user_id: int) -> str:
    c = await get_client(user_id)
    if c and len(c) >= 5 and c[4]:
        return c[4]
    return "it"

async def upsert_client(tg_id: int, phone: str | None, surname: str | None, name: str | None, lang: str | None):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id FROM clients WHERE tg_id=?", (tg_id,))
        existing = await cur.fetchone()

        if existing:
            await db.execute(
                "UPDATE clients SET phone=COALESCE(?, phone), surname=COALESCE(?, surname), name=COALESCE(?, name), lang=COALESCE(?, lang) WHERE tg_id=?",
                (phone, surname, name, lang, tg_id)
            )
        else:
            await db.execute(
                "INSERT INTO clients (tg_id, phone, surname, name, lang, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (tg_id, phone, surname, name, lang, now)
            )
        await db.commit()

async def create_ticket(client_tg_id: int, service: str) -> str:
    ticket_id = gen_ticket_id()
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tickets (ticket_id, client_tg_id, service, status, assigned_operator_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ticket_id, client_tg_id, service, "new", None, now, now))
        await db.commit()
    return ticket_id

async def get_ticket(ticket_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ticket_id, client_tg_id, service, status, assigned_operator_id
            FROM tickets WHERE ticket_id=?
        """, (ticket_id,))
        return await cur.fetchone()

async def get_open_ticket_by_client(client_tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ticket_id, service, status
            FROM tickets
            WHERE client_tg_id=? AND status IN ('new','in_progress')
            ORDER BY updated_at DESC LIMIT 1
        """, (client_tg_id,))
        return await cur.fetchone()

async def set_ticket_status(ticket_id: str, status: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET status=?, updated_at=? WHERE ticket_id=?", (status, now, ticket_id))
        await db.commit()

async def assign_ticket(ticket_id: str, operator_id: int):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # allow claim if NULL only
        await db.execute("""
            UPDATE tickets
            SET assigned_operator_id=?, status='in_progress', updated_at=?
            WHERE ticket_id=? AND assigned_operator_id IS NULL
        """, (operator_id, now, ticket_id))
        await db.commit()

async def log_message(ticket_id: str, from_role: str, text: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO messages (ticket_id, from_role, text, created_at)
            VALUES (?, ?, ?, ?)
        """, (ticket_id, from_role, text, now))
        await db.commit()


# =========================
# KEYBOARDS
# =========================
def kb_lang():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang:uk"),
            InlineKeyboardButton(text="🇮🇹 Italiano", callback_data="lang:it"),
        ]
    ])

def kb_share_phone(lang: str):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=T[lang]["btn_share_phone"], request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def kb_main_menu(lang: str):
    rows = []
    for key, label in SERVICE_KEYS:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"svc:{key}")])
    rows.append([InlineKeyboardButton(text=tr(lang, "talk_to_operator"), callback_data="op:choose")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_service(lang: str, service_key: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang, "docs_btn"), callback_data=f"info:{service_key}:docs")],
        [InlineKeyboardButton(text=tr(lang, "price_btn"), callback_data=f"info:{service_key}:price")],
        [InlineKeyboardButton(text=tr(lang, "wa_btn"), callback_data=f"wa:{service_key}")],
        [InlineKeyboardButton(text=tr(lang, "tg_btn"), callback_data=f"tgop:{service_key}")],
        [InlineKeyboardButton(text=tr(lang, "back_btn"), callback_data="back:menu")],
    ])

def kb_operator_choice(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang, "wa_recommended"), callback_data="op:wa")],
        [InlineKeyboardButton(text=tr(lang, "tg_here"), callback_data="op:tg")],
        [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:menu")],
    ])

def kb_ticket_actions(lang: str, ticket_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=tr(lang, "claim_btn"), callback_data=f"t:claim:{ticket_id}"),
            InlineKeyboardButton(text=tr(lang, "reply_btn"), callback_data=f"t:reply:{ticket_id}")
        ],
        [InlineKeyboardButton(text=tr(lang, "close_btn"), callback_data=f"t:close:{ticket_id}")]
    ])


# =========================
# BOT / DISPATCHER
# =========================
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


# =========================
# LANGUAGE set
# =========================
@dp.callback_query(F.data.startswith("lang:"))
async def set_language(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split(":")[1]
    if lang not in ("it", "uk"):
        lang = "it"

    await upsert_client(cb.from_user.id, phone=None, surname=None, name=None, lang=lang)
    await cb.answer("OK")

    client = await get_client(cb.from_user.id)
    # if fully registered -> menu
    if client and client[1] and client[2] and client[3]:
        await cb.message.answer(tr(lang, "welcome_registered"), reply_markup=ReplyKeyboardRemove())
        await cb.message.answer(tr(lang, "menu"), reply_markup=kb_main_menu(lang))
        return

    # else registration
    await state.set_state(RegStates.wait_phone)
    await cb.message.answer(tr(lang, "welcome_need_phone"), reply_markup=kb_share_phone(lang))


# =========================
# COMMANDS
# =========================
@dp.message(Command("whoami"))
async def whoami(message: Message):
    lang = await get_lang(message.from_user.id)
    await message.answer(f"ID: {message.from_user.id}\nADMIN: {is_admin(message.from_user.id)}\nLANG: {lang}")

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    lang = await get_lang(message.from_user.id)
    if not is_admin(message.from_user.id):
        await message.answer(tr(lang, "admin_denied"))
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang, "admin_new"), callback_data="adm:list:new")],
        [InlineKeyboardButton(text=tr(lang, "admin_progress"), callback_data="adm:list:in_progress")],
        [InlineKeyboardButton(text=tr(lang, "admin_closed"), callback_data="adm:list:closed")],
        [InlineKeyboardButton(text=tr(lang, "admin_search"), callback_data="adm:search:ask")],
    ])
    await message.answer(tr(lang, "admin_title"), reply_markup=kb)

@dp.callback_query(F.data.startswith("adm:list:"))
async def admin_list(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        await cb.answer(tr(lang, "admin_denied"), show_alert=True)
        return

    status = cb.data.split(":")[2]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ticket_id, service, status
            FROM tickets WHERE status=?
            ORDER BY updated_at DESC LIMIT 15
        """, (status,))
        rows = await cur.fetchall()

    if not rows:
        await cb.message.answer(tr(lang, "tickets_none"))
        await cb.answer()
        return

    lines = [f"• <b>{r[0]}</b> — {r[1]} — <i>{r[2]}</i>" for r in rows]
    await cb.message.answer(tr(lang, "tickets_list", lines="\n".join(lines)))
    await cb.answer()

@dp.callback_query(F.data == "adm:search:ask")
async def admin_search_ask(cb: CallbackQuery, state: FSMContext):
    lang = await get_lang(cb.from_user.id)
    if not is_admin(cb.from_user.id):
        await cb.answer(tr(lang, "admin_denied"), show_alert=True)
        return
    await state.set_state(AdminSearch.wait_ticket_id)
    await cb.message.answer(tr(lang, "admin_search_ask"))
    await cb.answer()

@dp.message(AdminSearch.wait_ticket_id)
async def admin_search_do(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    if not is_admin(message.from_user.id):
        await message.answer(tr(lang, "admin_denied"))
        return

    ticket_id = (message.text or "").strip()
    t = await get_ticket(ticket_id)
    if not t:
        await message.answer(tr(lang, "ticket_not_found"))
        await state.clear()
        return

    assigned = str(t[4]) if t[4] else "—"
    await message.answer(
        tr(lang, "ticket_found", id=t[0], service=t[2], status=t[3], assigned=assigned),
        reply_markup=kb_ticket_actions(lang, ticket_id)
    )
    await state.clear()


# =========================
# START / REGISTRATION
# =========================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    client = await get_client(message.from_user.id)
    lang = client[4] if client and len(client) >= 5 and client[4] in ("it", "uk") else None

    if not lang:
        await message.answer(tr("it", "choose_lang") + "\n" + tr("uk", "choose_lang"), reply_markup=kb_lang())
        return

    # if registered -> menu
    if client and client[1] and client[2] and client[3]:
        await message.answer(tr(lang, "welcome_registered"), reply_markup=ReplyKeyboardRemove())
        await message.answer(tr(lang, "menu"), reply_markup=kb_main_menu(lang))
        return

    await state.set_state(RegStates.wait_phone)
    await message.answer(tr(lang, "welcome_need_phone"), reply_markup=kb_share_phone(lang))

@dp.message(RegStates.wait_phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    phone = message.contact.phone_number
    await upsert_client(message.from_user.id, phone=phone, surname=None, name=None, lang=None)
    await state.set_state(RegStates.wait_surname)
    await message.answer(tr(lang, "enter_surname"), reply_markup=ReplyKeyboardRemove())

@dp.message(RegStates.wait_phone)
async def reg_phone_invalid(message: Message):
    lang = await get_lang(message.from_user.id)
    await message.answer(tr(lang, "use_share_phone"))

@dp.message(RegStates.wait_surname)
async def reg_surname(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    surname = (message.text or "").strip()
    await upsert_client(message.from_user.id, phone=None, surname=surname, name=None, lang=None)
    await state.set_state(RegStates.wait_name)
    await message.answer(tr(lang, "enter_name"))

@dp.message(RegStates.wait_name)
async def reg_name(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    name = (message.text or "").strip()
    await upsert_client(message.from_user.id, phone=None, surname=None, name=name, lang=None)
    await state.clear()
    await message.answer(tr(lang, "done", name=name))
    await message.answer(tr(lang, "menu"), reply_markup=kb_main_menu(lang))


# =========================
# MENU CALLBACKS
# =========================
@dp.callback_query(F.data == "back:menu")
async def back_menu(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    await cb.message.edit_text(tr(lang, "select_service"), reply_markup=kb_main_menu(lang))
    await cb.answer()

@dp.callback_query(F.data.startswith("svc:"))
async def service_selected(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    service_key = cb.data.split(":", 1)[1]
    await cb.message.edit_text(tr(lang, "service_title", service=service_key), reply_markup=kb_service(lang, service_key))
    await cb.answer()

@dp.callback_query(F.data.startswith("info:"))
async def info_selected(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    _, service_key, kind = cb.data.split(":")
    if kind == "docs":
        txt = DOCS.get(lang, {}).get(service_key, "—")
        await cb.answer()
        await cb.message.answer(tr(lang, "docs_title", service=service_key, txt=txt))
    else:
        txt = PRICE.get(lang, {}).get(service_key, "—")
        await cb.answer()
        await cb.message.answer(tr(lang, "price_title", service=service_key, txt=txt))

@dp.callback_query(F.data == "op:choose")
async def operator_choose(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    await cb.message.answer(tr(lang, "choose_operator_where"), reply_markup=kb_operator_choice(lang))
    await cb.answer()

@dp.callback_query(F.data == "op:wa")
async def op_wa(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    client = await get_client(cb.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    chosen = choose_whatsapp_for_client(cb.from_user.id)
    txt = f"Ciao! Sono {name} {surname}. Telefono: +{phone}. Vorrei assistenza da Doloni Documenti."
    link = wa_link(chosen, txt)
    await cb.message.answer(tr(lang, "open_whatsapp", link=link))
    await cb.answer()

@dp.callback_query(F.data == "op:tg")
async def op_tg(cb: CallbackQuery, state: FSMContext):
    lang = await get_lang(cb.from_user.id)
    await state.set_state(TicketStates.wait_client_message)
    await state.update_data(preselected_service="Generale")
    await cb.message.answer(tr(lang, "write_to_operator"))
    await cb.answer()

@dp.callback_query(F.data.startswith("wa:"))
async def service_wa(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    service_key = cb.data.split(":", 1)[1]

    client = await get_client(cb.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    chosen = choose_whatsapp_for_client(cb.from_user.id)
    txt = f"Ciao! Sono {name} {surname}. Telefono: +{phone}. Servizio: {service_key}. Vorrei assistenza."
    link = wa_link(chosen, txt)
    await cb.message.answer(tr(lang, "open_whatsapp_service", service=service_key, link=link))
    await cb.answer()

@dp.callback_query(F.data.startswith("tgop:"))
async def service_tg_operator(cb: CallbackQuery, state: FSMContext):
    lang = await get_lang(cb.from_user.id)
    service_key = cb.data.split(":", 1)[1]
    await state.set_state(TicketStates.wait_client_message)
    await state.update_data(preselected_service=service_key)
    await cb.message.answer(tr(lang, "write_to_operator_for", service=service_key))
    await cb.answer()


# =========================
# CLIENT -> ticket (first message)
# =========================
@dp.message(TicketStates.wait_client_message)
async def client_message_for_ticket(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()
    service = data.get("preselected_service") or "Generale"

    existing = await get_open_ticket_by_client(message.from_user.id)
    if existing:
        ticket_id = existing[0]
        is_new = False
    else:
        ticket_id = await create_ticket(message.from_user.id, service)
        is_new = True

    msg_text = (message.text or "").strip()
    await log_message(ticket_id, "client", msg_text)

    client = await get_client(message.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    if OPERATORS_GROUP_ID != 0:
        txt = tr(lang, "ticket_text_new" if is_new else "ticket_text_msg",
                 ticket=ticket_id, name=name, surname=surname, phone=phone, service=service, msg=msg_text)
        await bot.send_message(OPERATORS_GROUP_ID, txt, reply_markup=kb_ticket_actions(lang, ticket_id))
    else:
        log.warning("OPERATORS_GROUP_ID not set. Can't notify operators.")

    await message.answer(tr(lang, "request_sent", ticket=ticket_id))

    # IMPORTANT: exit state so next messages are handled by catch-all
    await state.clear()


# =========================
# TICKET ACTIONS (operators group)
# =========================
@dp.callback_query(F.data.startswith("t:claim:"))
async def ticket_claim(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer(tr(lang, "only_operators"), show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer(tr(lang, "ticket_not_found"), show_alert=True)
        return

    if t[4] is not None and t[4] != cb.from_user.id:
        await cb.answer(tr(lang, "already_taken"), show_alert=True)
        return

    await assign_ticket(ticket_id, cb.from_user.id)
    await cb.answer(tr(lang, "taken_ok"))

@dp.callback_query(F.data.startswith("t:reply:"))
async def ticket_reply(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer(tr(lang, "only_operators"), show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer(tr(lang, "ticket_not_found"), show_alert=True)
        return

    assigned = t[4]
    if assigned is None:
        await assign_ticket(ticket_id, cb.from_user.id)
    elif assigned != cb.from_user.id:
        await cb.answer(tr(lang, "assigned_other"), show_alert=True)
        return

    ACTIVE_TICKET[cb.from_user.id] = ticket_id
    await bot.send_message(cb.from_user.id, tr(lang, "active_chat_on", ticket=ticket_id))
    await cb.answer("OK")

@dp.callback_query(F.data.startswith("t:close:"))
async def ticket_close(cb: CallbackQuery):
    lang = await get_lang(cb.from_user.id)
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer(tr(lang, "only_operators"), show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer(tr(lang, "ticket_not_found"), show_alert=True)
        return

    assigned = t[4]
    if assigned is not None and assigned != cb.from_user.id:
        await cb.answer(tr(lang, "assigned_other"), show_alert=True)
        return

    await set_ticket_status(ticket_id, "closed")
    await cb.answer("OK")

    # remove active chat for this operator if it points to this ticket
    if ACTIVE_TICKET.get(cb.from_user.id) == ticket_id:
        ACTIVE_TICKET.pop(cb.from_user.id, None)

    # notify client in their language
    client_lang = await get_lang(t[1])
    try:
        await bot.send_message(t[1], tr(client_lang, "ticket_closed"))
    except Exception:
        pass

    if OPERATORS_GROUP_ID != 0:
        await bot.send_message(OPERATORS_GROUP_ID, f"🔒 <b>{ticket_id}</b> closed.")


# =========================
# OPERATOR private chat mode
# =========================
@dp.message(Command("stop"))
async def stop_active_chat(message: Message):
    lang = await get_lang(message.from_user.id)
    if not is_admin(message.from_user.id):
        return
    if message.from_user.id in ACTIVE_TICKET:
        tid = ACTIVE_TICKET.pop(message.from_user.id, None)
        await message.answer(tr(lang, "active_chat_off", ticket=tid or "—"))
    else:
        await message.answer(tr(lang, "no_active_chat"))

@dp.message(F.private)
async def private_messages_router(message: Message):
    """
    In private:
    - if admin and has ACTIVE_TICKET -> send to client
    - if admin without active -> show hint
    - if client -> normal flow (menu/help)
    """
    # ignore commands handled elsewhere
    if is_command_text(message.text):
        return

    if is_admin(message.from_user.id):
        lang = await get_lang(message.from_user.id)
        ticket_id = ACTIVE_TICKET.get(message.from_user.id)

        if not ticket_id:
            await message.answer(tr(lang, "hint_admin"))
            return

        t = await get_ticket(ticket_id)
        if not t:
            ACTIVE_TICKET.pop(message.from_user.id, None)
            await message.answer(tr(lang, "ticket_not_found"))
            return

        text = (message.text or "").strip()
        if not text:
            return

        await log_message(ticket_id, "operator", text)

        client_tg_id = t[1]

        # ✅ DEBUG: показати куди саме відправляємо
        await message.answer(f"🔎 DEBUG: ticket={ticket_id} -> client_tg_id={client_tg_id}")

        try:
            await bot.send_message(client_tg_id, f"<b>Doloni Documenti:</b>\n{text}")
            await message.answer(tr(lang, "sent_ok"))
        except Exception as e:
            log.exception("Failed to send message to client %s for ticket %s", client_tg_id, ticket_id)
            await message.answer(f"❌ Не вдалося надіслати клієнту.\nПомилка: {type(e).__name__}: {e}")
        return

    @dp.message(Command("ticket"))
    async def ticket_info(message: Message):
        if not is_admin(message.from_user.id):
            return
        ticket_id = ACTIVE_TICKET.get(message.from_user.id)
        if not ticket_id:
            await message.answer("ACTIVE_TICKET: None (натисни ✉️ Rispondi на тікеті в групі)")
            return
        t = await get_ticket(ticket_id)
        await message.answer(f"TICKET: {t}")

    # client in private: continue conversation if ticket open, else show menu
    lang = await get_lang(message.from_user.id)
    open_ticket = await get_open_ticket_by_client(message.from_user.id)
    if not open_ticket:
        await message.answer(tr(lang, "select_service"), reply_markup=kb_main_menu(lang))
        return

    ticket_id = open_ticket[0]
    text = (message.text or "").strip()
    if not text:
        return

    await log_message(ticket_id, "client", text)

    client = await get_client(message.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    t = await get_ticket(ticket_id)
    assigned_operator_id = t[4] if t else None

    # notify assigned operator in private (auto-activate)
    if assigned_operator_id:
        try:
            await bot.send_message(
                assigned_operator_id,
                tr(lang, "ticket_text_msg", ticket=ticket_id, name=name, surname=surname, phone=phone, msg=text)
            )
            ACTIVE_TICKET[assigned_operator_id] = ticket_id
        except Exception:
            pass

    # also notify operators group (so nothing is lost)
    if OPERATORS_GROUP_ID != 0:
        await bot.send_message(
            OPERATORS_GROUP_ID,
            tr(lang, "ticket_text_msg", ticket=ticket_id, name=name, surname=surname, phone=phone, msg=text),
            reply_markup=kb_ticket_actions(lang, ticket_id)
        )


# =========================
# FALLBACK: non-private chats (groups etc.)
# =========================
@dp.message()
async def non_private_fallback(message: Message):
    """
    If someone writes to bot in a group/chat:
    - Usually ignore, or show minimal help.
    """
    # Many bots are used only in private. We'll just ignore to avoid noise.
    return


# =========================
# MAIN
# =========================
async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing in .env")

    await init_db()
    log.info("Bot starting... ADMIN_IDS=%s OPERATORS_GROUP_ID=%s", ADMIN_IDS, OPERATORS_GROUP_ID)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
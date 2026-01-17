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

WA1 = "393920725322"
WA2 = "393286058012"

DB_PATH = "doloni.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("doloni-bot")


# =========================
# FSM (solo client)
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
# PENDING REPLY (admin)
# operator_id -> ticket_id
# =========================
# operator_id -> ticket_id (active chat session)
ACTIVE_TICKET: dict[int, str] = {}


# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_command_text(text: str | None) -> bool:
    return bool(text) and text.strip().startswith("/")


def choose_whatsapp_for_client(tg_id: int) -> str:
    # stable distribution: even -> WA1, odd -> WA2
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
            created_at TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            client_tg_id INTEGER,
            service TEXT,
            status TEXT,
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
        cur = await db.execute("SELECT tg_id, phone, surname, name FROM clients WHERE tg_id=?", (tg_id,))
        return await cur.fetchone()


async def upsert_client(tg_id: int, phone: str | None, surname: str | None, name: str | None):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id FROM clients WHERE tg_id=?", (tg_id,))
        existing = await cur.fetchone()

        if existing:
            await db.execute(
                "UPDATE clients SET phone=COALESCE(?, phone), surname=COALESCE(?, surname), name=COALESCE(?, name) WHERE tg_id=?",
                (phone, surname, name, tg_id)
            )
        else:
            await db.execute(
                "INSERT INTO clients (tg_id, phone, surname, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (tg_id, phone, surname, name, now)
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
            ORDER BY created_at DESC LIMIT 1
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
def kb_share_phone():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Condividi numero", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def kb_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 ISEE", callback_data="svc:ISEE")],
        [InlineKeyboardButton(text="📑 730", callback_data="svc:730")],
        [InlineKeyboardButton(text="🚗 Conversione patente", callback_data="svc:Patente")],
        [InlineKeyboardButton(text="📄 Permesso di soggiorno", callback_data="svc:Permesso")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Assegno Unico", callback_data="svc:AssegnoUnico")],
        [InlineKeyboardButton(text="🤝 Assegno di Inclusione (ADI)", callback_data="svc:ADI")],
        [InlineKeyboardButton(text="💬 Parlare con un operatore", callback_data="op:choose")],
    ])


def kb_service(service: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Documenti necessari", callback_data=f"info:{service}:docs")],
        [InlineKeyboardButton(text="💶 Prezzo indicativo", callback_data=f"info:{service}:price")],
        [InlineKeyboardButton(text="💬 Continua su WhatsApp", callback_data=f"wa:{service}")],
        [InlineKeyboardButton(text="💬 Operatore su Telegram", callback_data=f"tgop:{service}")],
        [InlineKeyboardButton(text="⬅️ Torna ai servizi", callback_data="back:menu")],
    ])


def kb_operator_choice():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 WhatsApp (consigliato)", callback_data="op:wa")],
        [InlineKeyboardButton(text="💬 Telegram (qui)", callback_data="op:tg")],
        [InlineKeyboardButton(text="⬅️ Indietro", callback_data="back:menu")],
    ])


def kb_ticket_actions(ticket_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Prendi in carico", callback_data=f"t:claim:{ticket_id}"),
            InlineKeyboardButton(text="✉️ Rispondi", callback_data=f"t:reply:{ticket_id}")
        ],
        [InlineKeyboardButton(text="🔒 Chiudi", callback_data=f"t:close:{ticket_id}")]
    ])


# =========================
# CONTENT
# =========================
DOCS = {
    "ISEE": "- Documento d’identità\n- Codice fiscale\n- Contratto di affitto (se presente)\n- Saldo e giacenza media conti\n- CU / redditi (se presenti)\n- Stato di famiglia",
    "730": "- Documento e codice fiscale\n- CU\n- Spese mediche\n- Spese affitto / mutuo\n- Altre detrazioni",
    "Patente": "- Patente estera\n- Documento d’identità\n- Codice fiscale\n- Certificato medico\n- Residenza / domicilio in Italia",
    "Permesso": "- Passaporto\n- Permesso di soggiorno (se rinnovo)\n- Contratto di lavoro / reddito\n- Residenza o ospitalità",
    "AssegnoUnico": "- Documento e codice fiscale genitori\n- Codici fiscali figli\n- ISEE valido\n- IBAN",
    "ADI": "- Documento e codice fiscale\n- ISEE valido\n- Stato di famiglia\n- IBAN\n- Altri requisiti INPS"
}

PRICE = {
    "ISEE": "A partire da €50, in base alla situazione familiare.",
    "730": "A partire da €60.",
    "Patente": "Il costo varia in base al caso. Ti daremo un preventivo preciso su WhatsApp.",
    "Permesso": "Il costo dipende dal tipo di permesso. Valutazione gratuita iniziale.",
    "AssegnoUnico": "A partire da €40.",
    "ADI": "Preventivo personalizzato in base al caso."
}


# =========================
# BOT / DISPATCHER
# =========================
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())


# =========================
# COMMANDS
# =========================
@dp.message(Command("whoami"))
async def whoami(message: Message):
    await message.answer(f"ID: {message.from_user.id}\nADMIN: {is_admin(message.from_user.id)}")


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Accesso negato.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Nuovi", callback_data="adm:list:new")],
        [InlineKeyboardButton(text="⏳ In lavorazione", callback_data="adm:list:in_progress")],
        [InlineKeyboardButton(text="✅ Chiusi", callback_data="adm:list:closed")],
        [InlineKeyboardButton(text="🔎 Cerca (scrivi ID)", callback_data="adm:search:ask")],
    ])
    await message.answer("🛠️ <b>Doloni Admin</b>", reply_markup=kb)


@dp.callback_query(F.data.startswith("adm:list:"))
async def admin_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("No access", show_alert=True)
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
        await cb.message.answer("Nessun ticket in questa lista.")
        await cb.answer()
        return

    lines = [f"• <b>{r[0]}</b> — {r[1]} — <i>{r[2]}</i>" for r in rows]
    await cb.message.answer("📋 Tickets:\n" + "\n".join(lines))
    await cb.answer()


@dp.callback_query(F.data == "adm:search:ask")
async def admin_search_ask(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("No access", show_alert=True)
        return
    await state.set_state(AdminSearch.wait_ticket_id)
    await cb.message.answer("Scrivi l’ID del ticket (es: DD-2026-123456).")
    await cb.answer()


@dp.message(AdminSearch.wait_ticket_id)
async def admin_search_do(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Accesso negato.")
        return

    ticket_id = message.text.strip()
    t = await get_ticket(ticket_id)
    if not t:
        await message.answer("Ticket non trovato.")
        await state.clear()
        return

    await message.answer(
        f"✅ Trovato: <b>{t[0]}</b>\nServizio: {t[2]}\nStatus: {t[3]}\nAssegnato: {t[4] or '—'}",
        reply_markup=kb_ticket_actions(ticket_id)
    )
    await state.clear()


# =========================
# START / REGISTRATION
# =========================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    client = await get_client(message.from_user.id)
    if client and client[1] and client[2] and client[3]:
        await message.answer(
            "👋 Benvenuto/a in <b>Doloni Documenti</b>.\nSeleziona un servizio ⬇️",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer("Menu:", reply_markup=kb_main_menu())
        return

    await state.set_state(RegStates.wait_phone)
    await message.answer(
        "👋 Benvenuto/a in <b>Doloni Documenti</b>\nPer iniziare, condividi il tuo numero di telefono.",
        reply_markup=kb_share_phone()
    )


@dp.message(RegStates.wait_phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await upsert_client(message.from_user.id, phone=phone, surname=None, name=None)
    await state.set_state(RegStates.wait_surname)
    await message.answer("Grazie! Inserisci il tuo <b>Cognome</b>.", reply_markup=ReplyKeyboardRemove())


@dp.message(RegStates.wait_phone)
async def reg_phone_invalid(message: Message):
    await message.answer("Per favore usa il pulsante <b>Condividi numero</b>.")


@dp.message(RegStates.wait_surname)
async def reg_surname(message: Message, state: FSMContext):
    surname = (message.text or "").strip()
    await upsert_client(message.from_user.id, phone=None, surname=surname, name=None)
    await state.set_state(RegStates.wait_name)
    await message.answer("Ora inserisci il tuo <b>Nome</b>.")


@dp.message(RegStates.wait_name)
async def reg_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    await upsert_client(message.from_user.id, phone=None, surname=None, name=name)
    await state.clear()
    await message.answer(f"✅ Perfetto, <b>{name}</b>!\nSeleziona il servizio di tuo interesse ⬇️")
    await message.answer("Menu:", reply_markup=kb_main_menu())


# =========================
# MENU CALLBACKS
# =========================
@dp.callback_query(F.data == "back:menu")
async def back_menu(cb: CallbackQuery):
    await cb.message.edit_text("Seleziona un servizio ⬇️", reply_markup=kb_main_menu())
    await cb.answer()


@dp.callback_query(F.data.startswith("svc:"))
async def service_selected(cb: CallbackQuery):
    service = cb.data.split(":", 1)[1]
    await cb.message.edit_text(f"<b>{service}</b>\nSeleziona cosa vuoi fare:", reply_markup=kb_service(service))
    await cb.answer()


@dp.callback_query(F.data.startswith("info:"))
async def info_selected(cb: CallbackQuery):
    _, service, kind = cb.data.split(":")
    if kind == "docs":
        text = DOCS.get(service, "Info non disponibile.")
        await cb.answer()
        await cb.message.answer(f"<b>{service}</b> — Documenti necessari:\n{text}")
    else:
        text = PRICE.get(service, "Info non disponibile.")
        await cb.answer()
        await cb.message.answer(f"<b>{service}</b> — Prezzo indicativo:\n{text}")


@dp.callback_query(F.data == "op:choose")
async def operator_choose(cb: CallbackQuery):
    await cb.message.answer("Vuoi continuare su WhatsApp oppure parlare qui su Telegram?", reply_markup=kb_operator_choice())
    await cb.answer()


@dp.callback_query(F.data == "op:wa")
async def op_wa(cb: CallbackQuery):
    client = await get_client(cb.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""
    chosen = choose_whatsapp_for_client(cb.from_user.id)
    txt = f"Ciao! Sono {name} {surname}. Telefono: +{phone}. Vorrei assistenza da Doloni Documenti."
    link = wa_link(chosen, txt)
    await cb.message.answer(f"📲 Apri WhatsApp: {link}")
    await cb.answer()


@dp.callback_query(F.data == "op:tg")
async def op_tg(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TicketStates.wait_client_message)
    await cb.message.answer("💬 Scrivi qui il tuo messaggio per l’operatore.\nTi risponderemo qui su Telegram.")
    await cb.answer()


@dp.callback_query(F.data.startswith("wa:"))
async def service_wa(cb: CallbackQuery):
    service = cb.data.split(":", 1)[1]
    client = await get_client(cb.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""
    chosen = choose_whatsapp_for_client(cb.from_user.id)
    txt = f"Ciao! Sono {name} {surname}. Telefono: +{phone}. Servizio: {service}. Vorrei assistenza."
    link = wa_link(chosen, txt)
    await cb.message.answer(f"📲 WhatsApp ({service}): {link}")
    await cb.answer()


@dp.callback_query(F.data.startswith("tgop:"))
async def service_tg_operator(cb: CallbackQuery, state: FSMContext):
    service = cb.data.split(":", 1)[1]
    await state.update_data(preselected_service=service)
    await state.set_state(TicketStates.wait_client_message)
    await cb.message.answer(f"💬 Scrivi il tuo messaggio per <b>{service}</b>.\nTi risponderemo qui su Telegram.")
    await cb.answer()


# =========================
# CLIENT -> TICKET
# =========================
@dp.message(TicketStates.wait_client_message)
async def client_message_for_ticket(message: Message, state: FSMContext):
    data = await state.get_data()
    service = data.get("preselected_service") or "Generale"

    existing = await get_open_ticket_by_client(message.from_user.id)
    if existing:
        ticket_id = existing[0]
        is_new = False
    else:
        ticket_id = await create_ticket(message.from_user.id, service)
        is_new = True

    await log_message(ticket_id, "client", message.text or "")

    client = await get_client(message.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    prefix = "🆕" if is_new else "📩"

    if OPERATORS_GROUP_ID != 0:
        text = (
            f"{prefix} <b>Ticket {ticket_id}</b>\n"
            f"Cliente: {name} {surname}\n"
            f"Tel: +{phone}\n"
            f"Servizio: {service}\n"
            f"Messaggio: “{message.text}”"
        )
        await bot.send_message(
            OPERATORS_GROUP_ID,
            text,
            reply_markup=kb_ticket_actions(ticket_id)
        )

    await message.answer(
        f"✅ Richiesta inviata a <b>Doloni Documenti</b>.\n"
        f"<b>ID:</b> {ticket_id}\n"
        f"Ti risponderemo qui."
    )

    # 🔥 КРИТИЧНО: виходимо зі state
    await state.clear()


# =========================
# TICKET ACTIONS (GROUP)
# =========================
@dp.callback_query(F.data.startswith("t:claim:"))
async def ticket_claim(cb: CallbackQuery):
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer("Solo operatori.", show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer("Ticket non trovato.", show_alert=True)
        return

    if t[4] is not None and t[4] != cb.from_user.id:
        await cb.answer("Già preso da un altro operatore.", show_alert=True)
        return

    await assign_ticket(ticket_id, cb.from_user.id)
    await cb.answer("Preso in carico ✅")


@dp.callback_query(F.data.startswith("t:reply:"))
async def ticket_reply(cb: CallbackQuery):
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer("Solo operatori.", show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer("Ticket non trovato.", show_alert=True)
        return

    assigned = t[4]
    if assigned is None:
        await assign_ticket(ticket_id, cb.from_user.id)
    elif assigned != cb.from_user.id:
        await cb.answer("Ticket assegnato a un altro operatore.", show_alert=True)
        return

    # ✅ set active dialog for this operator
    ACTIVE_TICKET[cb.from_user.id] = ticket_id

    await bot.send_message(
        cb.from_user.id,
        f"✅ Chat attiva: <b>{ticket_id}</b>\n"
        f"Ora puoi scrivere qui in privato: ogni messaggio verrà inviato al cliente.\n"
        f"Per uscire: /stop"
    )
    await cb.answer("Chat attiva in privato ✅")

@dp.message(Command("stop"))
async def stop_active_chat(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.from_user.id in ACTIVE_TICKET:
        tid = ACTIVE_TICKET.pop(message.from_user.id, None)
        await message.answer(f"⛔️ Chat disattivata (era: <b>{tid}</b>).")
    else:
        await message.answer("Non hai una chat attiva.")

@dp.callback_query(F.data.startswith("t:close:"))
async def ticket_close(cb: CallbackQuery):
    ticket_id = cb.data.split(":")[2]
    if not is_admin(cb.from_user.id):
        await cb.answer("Solo operatori.", show_alert=True)
        return

    t = await get_ticket(ticket_id)
    if not t:
        await cb.answer("Ticket non trovato.", show_alert=True)
        return

    assigned = t[4]
    if assigned is not None and assigned != cb.from_user.id:
        await cb.answer("Ticket assegnato a un altro operatore.", show_alert=True)
        return

    await set_ticket_status(ticket_id, "closed")
    await cb.answer("Chiuso 🔒")

    try:
        await bot.send_message(t[1], "✅ La conversazione è stata chiusa.\nSe hai bisogno, scrivi di nuovo qui.")
    except Exception:
        pass

    if OPERATORS_GROUP_ID != 0:
        await bot.send_message(OPERATORS_GROUP_ID, f"🔒 Ticket <b>{ticket_id}</b> chiuso.")



# =========================
# CLIENT catch-all (must be after admin handler)
# =========================

@dp.message(F.from_user.id.in_(ADMIN_IDS))
async def admin_reply_or_hint(message: Message, state: FSMContext):
    if is_command_text(message.text):
        return

    ticket_id = ACTIVE_TICKET.get(message.from_user.id)
    if ticket_id:
        t = await get_ticket(ticket_id)
        if not t:
            ACTIVE_TICKET.pop(message.from_user.id, None)
            await message.answer("Ticket non trovato. Chat disattivata.")
            return

        client_tg_id = t[1]
        text = (message.text or "").strip()

        await log_message(ticket_id, "operator", text)
        await bot.send_message(client_tg_id, f"{text}")
        return

    await message.answer(
        "🛠️ Sei in modalità amministratore.\n"
        "Apri una chat: nella chat operatori premi ✉️ Rispondi su un ticket.\n"
        "Poi scrivi qui in privato.\n"
        "Uscire: /stop"
    )


@dp.message(~F.from_user.id.in_(ADMIN_IDS))
async def client_catch_all(message: Message, state: FSMContext):
    if is_command_text(message.text):
        return

    # якщо клієнт ще в реєстрації/стані — не чіпаємо (aiogram сам піде в state-хендлери)
    # але якщо ти десь забув state.clear(), то це допоможе:
    cur_state = await state.get_state()
    if cur_state is not None:
        # тут нічого не робимо, хай state-хендлери відпрацюють
        return

    open_ticket = await get_open_ticket_by_client(message.from_user.id)
    if not open_ticket:
        await message.answer("Seleziona un servizio ⬇️", reply_markup=kb_main_menu())
        return

    ticket_id = open_ticket[0]
    await log_message(ticket_id, "client", message.text or "")

    client = await get_client(message.from_user.id)
    phone = client[1] if client else ""
    surname = client[2] if client else ""
    name = client[3] if client else ""

    t = await get_ticket(ticket_id)
    assigned_operator_id = t[4] if t else None

    text = (
        f"📩 <b>Ticket {ticket_id}</b> (messaggio cliente)\n"
        f"{name} {surname} | +{phone}\n"
        f"“{message.text}”"
    )

    # В приват призначеному оператору (якщо є)
    if assigned_operator_id:
        try:
            await bot.send_message(assigned_operator_id, text)
            ACTIVE_TICKET[assigned_operator_id] = ticket_id
        except Exception:
            pass

    # І в групу операторів (щоб точно не губилось)
    if OPERATORS_GROUP_ID != 0:
        await bot.send_message(OPERATORS_GROUP_ID, text, reply_markup=kb_ticket_actions(ticket_id))


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
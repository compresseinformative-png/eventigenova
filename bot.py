"""
Bot Telegram — Aggregatore eventi Genova
"""

import os
import json
import logging
import argparse
import re
from datetime import datetime, date, timedelta
from pathlib import Path

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from scraper import scrape_mentelocale

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CACHE_DIR = Path("cache")
CACHE_MAX_AGE_ORE = 6

CACHE_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def get_eventi(filtro: str, force: bool = False) -> list[dict]:
    cache_file = CACHE_DIR / f"eventi_{filtro}.json"
    
    if not force and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            generato = datetime.fromisoformat(data["generato_il"])
            eta = (datetime.now() - generato).total_seconds() / 3600
            if eta < CACHE_MAX_AGE_ORE:
                log.info(f"Cache valida per '{filtro}' ({len(data['eventi'])} eventi)")
                return data["eventi"]
        except Exception as e:
            log.warning(f"Cache corrotta: {e}")
    
    log.info(f"Avvio scraping per '{filtro}'...")
    eventi = scrape_mentelocale(filtro=filtro)
    
    cache_file.write_text(
        json.dumps({
            "generato_il": datetime.now().isoformat(),
            "eventi": eventi
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    log.info(f"Scraping completato: {len(eventi)} eventi")
    return eventi


# --------------------------------------------------------------------------- #
# Formattazione
# --------------------------------------------------------------------------- #

def fmt_evento(e: dict, num: int) -> str:
    righe = [f"{num}. *{e['titolo']}*"]
    
    if e.get("data_raw"):
        righe.append(f"📅 {e['data_raw']}")
    
    if e.get("luogo"):
        righe.append(f"📍 {e['luogo']}")
    
    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")
    
    return "\n".join(righe)


async def invia_lista(update, eventi: list[dict], intestazione: str):
    if not eventi:
        await update.message.reply_text(f"{intestazione}\n\n_Nessun evento trovato_ 😔")
        return
    
    await update.message.reply_text(intestazione)
    
    # Invia in blocchi da 10
    for i in range(0, len(eventi), 10):
        blocco = eventi[i:i+10]
        messaggio = ""
        for idx, e in enumerate(blocco, start=i+1):
            messaggio += fmt_evento(e, idx) + "\n\n" + "—" * 20 + "\n\n"
        await update.message.reply_text(messaggio, parse_mode="Markdown", disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
# Digest (per cron job)
# --------------------------------------------------------------------------- #

async def invia_digest_settimana():
    bot = Bot(token=TOKEN)
    eventi_oggi = get_eventi("oggi")
    
    testo = f"☀️ *Buongiorno! Eventi a Genova — {date.today().strftime('%d/%m/%Y')}*\n\n"
    
    if eventi_oggi:
        for e in eventi_oggi[:5]:
            testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    else:
        testo += "_Nessun evento oggi_"
    
    testo += "\n_Scrivi /oggi per tutti i dettagli._"
    
    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=testo, parse_mode="Markdown")
    log.info("Digest inviato")


async def invia_digest_weekend():
    bot = Bot(token=TOKEN)
    eventi = get_eventi("weekend")
    
    if not eventi:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text="🎉 *WEEKEND*\n\n_Nessun evento trovato_", parse_mode="Markdown")
        return
    
    await bot.send_message(chat_id=ADMIN_CHAT_ID, text="🎉 *EVENTI DEL WEEKEND*", parse_mode="Markdown")
    
    for i, e in enumerate(eventi[:15], 1):
        msg = fmt_evento(e, i)
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
# Comandi
# --------------------------------------------------------------------------- #

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Eventi Genova*\n\n"
        "• /oggi — eventi di oggi\n"
        "• /domani — eventi di domani\n"
        "• /weekend — eventi del weekend\n"
        "• /cerca [parola] — cerca un evento\n"
        "• /aggiorna — aggiorna (admin)\n\n"
        "_Fonte: Mentelocale_",
        parse_mode="Markdown"
    )


async def cmd_oggi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("oggi")
    oggi = date.today()
    await invia_lista(update, eventi, f"🗓 *EVENTI OGGI — {oggi.strftime('%d/%m/%Y')}*\n")


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("domani")
    domani = date.today() + timedelta(days=1)
    await invia_lista(update, eventi, f"🗓 *EVENTI DOMANI — {domani.strftime('%d/%m/%Y')}*\n")


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("weekend")
    await invia_lista(update, eventi, f"🎉 *EVENTI WEEKEND*\n")


async def cmd_cerca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args).strip().lower()
    if not query:
        await update.message.reply_text("Uso: /cerca [parola]")
        return
    
    await update.message.reply_text(f"⏳ Cerco \"{query}\"...")
    
    tutti = []
    for filtro in ["oggi", "domani", "weekend"]:
        tutti.extend(get_eventi(filtro))
    
    filtrati = [e for e in tutti if query in e["titolo"].lower() or query in e["luogo"].lower()]
    
    if not filtrati:
        await update.message.reply_text(f"🔍 Nessun evento trovato per \"{query}\"")
        return
    
    await invia_lista(update, filtrati, f"🔍 *RISULTATI PER \"{query.upper()}\"*\n")


async def cmd_aggiorna(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Solo admin.")
        return
    
    await update.message.reply_text("⏳ Aggiornamento...")
    for filtro in ["oggi", "domani", "weekend"]:
        get_eventi(filtro, force=True)
    await update.message.reply_text("✅ Aggiornato!")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Prova /oggi, /domani, /weekend o /cerca")


# --------------------------------------------------------------------------- #
# Avvio
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--digest-weekend", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("Errore: TOKEN non impostato")

    if args.digest:
        import asyncio
        asyncio.run(invia_digest_settimana())
        return
    
    if args.digest_weekend:
        import asyncio
        asyncio.run(invia_digest_weekend())
        return

    log.info("Bot avviato!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oggi", cmd_oggi))
    app.add_handler(CommandHandler("domani", cmd_domani))
    app.add_handler(CommandHandler("weekend", cmd_weekend))
    app.add_handler(CommandHandler("cerca", cmd_cerca))
    app.add_handler(CommandHandler("aggiorna", cmd_aggiorna))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sconosciuto))
    app.run_polling()


if __name__ == "__main__":
    main()
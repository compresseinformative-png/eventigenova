"""
Bot Telegram — Aggregatore eventi Genova
"""

import os
import json
import logging
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from scraper import scrape_genovatoday, scrape_mentelocale, deduplica

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CACHE_FILE = Path("eventi_cache.json")
CACHE_MAX_AGE_ORE = 6

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def carica_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        log.info("Cache file non esiste")
        return []
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        generato = datetime.fromisoformat(data["generato_il"])
        età = (datetime.now() - generato).total_seconds() / 3600
        if età < CACHE_MAX_AGE_ORE:
            log.info(f"Cache valida ({età:.1f}h fa), {len(data['eventi'])} eventi")
            return data["eventi"]
        else:
            log.info(f"Cache scaduta ({età:.1f}h fa)")
    except Exception as e:
        log.warning(f"Cache corrotta: {e}")
    return []


def salva_cache(eventi: list[dict]):
    CACHE_FILE.write_text(
        json.dumps({"generato_il": datetime.now().isoformat(), "eventi": eventi},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Salvati {len(eventi)} eventi in cache")


def get_eventi(force: bool = False) -> list[dict]:
    if not force:
        cached = carica_cache()
        if cached:
            return cached
    log.info("Avvio scraping...")
    tutti = deduplica(scrape_genovatoday() + scrape_mentelocale())
    tutti.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    # DEBUG: stampa primi 3 eventi con data
    log.info("Primi 3 eventi scrapati:")
    for i, e in enumerate(tutti[:3]):
        log.info(f"  {i+1}. {e['titolo'][:50]}... data={e.get('data')}")
    
    salva_cache(tutti)
    log.info(f"Scraping completato: {len(tutti)} eventi")
    return tutti


# --------------------------------------------------------------------------- #
# Formattazione messaggi
# --------------------------------------------------------------------------- #

def fmt_evento(e: dict, num: int | None = None) -> str:
    righe = []
    if num:
        righe.append(f"*{num}. {e['titolo']}*")
    else:
        righe.append(f"*{e['titolo']}*")

    if e.get("data"):
        try:
            d = date.fromisoformat(e["data"])
            righe.append(f"📅 {d.strftime('%A %d %B').capitalize()}")
        except ValueError:
            righe.append(f"📅 {e.get('data_raw', '')}")
    elif e.get("data_raw"):
        righe.append(f"📅 {e['data_raw']}")
    else:
        righe.append(f"📅 Data non specificata")

    if e.get("luogo") and e["luogo"] != "Genova":
        righe.append(f"📍 {e['luogo']}")

    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")

    fonte = e.get("fonte", "")
    righe.append(f"_Fonte: {fonte}_")

    return "\n".join(righe)


def filtra_per_data(eventi: list[dict], target: date) -> list[dict]:
    filtrati = [e for e in eventi if e.get("data") == target.isoformat()]
    log.info(f"Filtro per data {target.isoformat()}: {len(filtrati)} eventi su {len(eventi)} totali")
    
    # DEBUG: mostra prime 5 date presenti negli eventi
    date_presenti = set()
    for e in eventi[:20]:
        if e.get("data"):
            date_presenti.add(e["data"])
    log.info(f"Prime date presenti nel cache: {sorted(date_presenti)[:5]}")
    
    return filtrati


def filtra_weekend(eventi: list[dict]) -> list[dict]:
    oggi = date.today()
    giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
    sabato = oggi + timedelta(days=giorni_a_sab)
    domenica = sabato + timedelta(days=1)
    filtrati = [
        e for e in eventi
        if e.get("data") in (sabato.isoformat(), domenica.isoformat())
    ]
    log.info(f"Weekend ({sabato.isoformat()}, {domenica.isoformat()}): {len(filtrati)} eventi")
    return filtrati


def invia_lista(eventi_filtrati: list[dict], intestazione: str) -> str:
    if not eventi_filtrati:
        return f"{intestazione}\n\n_Nessun evento trovato_ 😔"

    parti = [intestazione + "\n"]
    for i, e in enumerate(eventi_filtrati[:10], 1):
        parti.append(fmt_evento(e, i))
        parti.append("—" * 20)

    if len(eventi_filtrati) > 10:
        parti.append(f"_...e altri {len(eventi_filtrati) - 10} eventi. Usa /cerca per filtrare._")

    return "\n".join(parti)


# --------------------------------------------------------------------------- #
# Handler comandi
# --------------------------------------------------------------------------- #

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    testo = (
        "👋 *Benvenuto nell'aggregatore eventi di Genova!*\n\n"
        "Comandi disponibili:\n"
        "• /oggi — eventi di oggi\n"
        "• /domani — eventi di domani\n"
        "• /weekend — eventi del weekend\n"
        "• /cerca \\[parola\\] — cerca un evento\n"
        "• /aggiorna — forza aggiornamento\n"
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


async def cmd_oggi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di oggi...")
    eventi = get_eventi()
    log.info(f"Totale eventi in cache: {len(eventi)}")
    
    oggi = date.today()
    filtrati = filtra_per_data(eventi, oggi)
    
    testo = invia_lista(filtrati, f"🗓 *Eventi oggi — {oggi.strftime('%d/%m/%Y')}*")
    log.info(f"Invio risposta con {len(filtrati)} eventi")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di domani...")
    eventi = get_eventi()
    domani = date.today() + timedelta(days=1)
    filtrati = filtra_per_data(eventi, domani)
    testo = invia_lista(filtrati, f"🗓 *Eventi domani — {domani.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi del weekend...")
    eventi = get_eventi()
    filtrati = filtra_weekend(eventi)
    testo = invia_lista(filtrati, "🎉 *Eventi del weekend*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_cerca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args).strip().lower()
    if not query:
        await update.message.reply_text("Uso: /cerca \\[parola chiave\\]\nEsempio: /cerca jazz", parse_mode="Markdown")
        return

    await update.message.reply_text(f"⏳ Cerco \"{query}\"...")
    eventi = get_eventi()
    filtrati = [
        e for e in eventi
        if query in e.get("titolo", "").lower()
        or query in e.get("luogo", "").lower()
    ]
    testo = invia_lista(filtrati, f"🔍 *Risultati per \"{query}\"*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_aggiorna(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    await update.message.reply_text("⏳ Aggiornamento in corso, potrebbe richiedere 30-60 secondi...")
    eventi = get_eventi(force=True)
    await update.message.reply_text(f"✅ Aggiornato! Trovati *{len(eventi)} eventi*.", parse_mode="Markdown")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Non capisco 🤔 Prova con /oggi, /domani, /weekend o /cerca jazz"
    )


# --------------------------------------------------------------------------- #
# Digest mattutino
# --------------------------------------------------------------------------- #

async def invia_digest():
    from telegram import Bot
    bot = Bot(token=TOKEN)
    eventi = get_eventi()
    oggi_ev = filtra_per_data(eventi, date.today())
    domani_ev = filtra_per_data(eventi, date.today() + timedelta(days=1))

    testo = (
        f"☀️ *Buongiorno! Digest eventi Genova — {date.today().strftime('%d/%m/%Y')}*\n\n"
        f"📌 *Oggi ({len(oggi_ev)} eventi)*\n"
    )

    for e in oggi_ev[:5]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not oggi_ev:
        testo += "_Nessun evento_\n"

    testo += f"\n📌 *Domani ({len(domani_ev)} eventi)*\n"
    for e in domani_ev[:3]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not domani_ev:
        testo += "_Nessun evento_\n"

    testo += "\n_Scrivi /oggi o /weekend per i dettagli._"

    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=testo, parse_mode="Markdown")
    log.info("Digest inviato")


# --------------------------------------------------------------------------- #
# Avvio
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", action="store_true",
                        help="Invia il digest mattutino e termina (per cron)")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("Errore: variabile TOKEN non impostata")

    if args.digest:
        import asyncio
        asyncio.run(invia_digest())
        return

    log.info("Bot avviato, in ascolto...")
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
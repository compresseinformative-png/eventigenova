"""
Bot Telegram — Aggregatore eventi Genova
========================================

Comandi disponibili:
  /oggi       → eventi di oggi
  /domani     → eventi di domani
  /weekend    → eventi del prossimo weekend
  /cerca jazz → cerca eventi per parola chiave
  /aggiorna   → forza un nuovo scraping (solo admin)
  /svuota_cache → svuota la cache e ricarica (solo admin)

Setup:
  1. Crea un bot su Telegram parlando con @BotFather → ottieni TOKEN
  2. Scrivi al bot una volta, poi vai su:
       https://api.telegram.org/bot<TOKEN>/getUpdates
     e copia il tuo chat_id per ADMIN_CHAT_ID
  3. Installa dipendenze:
       pip install python-telegram-bot requests beautifulsoup4 lxml
  4. Avvia:
       TOKEN=xxx ADMIN_CHAT_ID=yyy python bot.py

Automazione mattutina:
  Aggiungere al crontab per digest giornaliero alle 08:00:
       0 8 * * * TOKEN=xxx ADMIN_CHAT_ID=yyy python /percorso/bot.py --digest
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

# importa le funzioni di scraping dal file scraper.py nella stessa cartella
from scraper import scrape_genovatoday, scrape_mentelocale, deduplica

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CACHE_FILE = Path("eventi_cache.json")
CACHE_MAX_AGE_ORE = 6

# FORCE_SCRAPE da variabile d'ambiente (su Railway: aggiungi FORCE_SCRAPE=true)
FORCE_SCRAPE = os.environ.get("FORCE_SCRAPE", "false").lower() == "true"

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
    # Se FORCE_SCRAPE è attivo, ignoro la cache
    if FORCE_SCRAPE:
        log.info("⚠️ FORCE_SCRAPE attivo - ignoro la cache")
        force = True
    
    if not force:
        cached = carica_cache()
        if cached:
            return cached
    
    log.info("Avvio scraping...")
    tutti = deduplica(scrape_genovatoday() + scrape_mentelocale())
    tutti.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    # DEBUG: stampa primi 5 eventi con data
    log.info("Primi 5 eventi scrapati:")
    for i, e in enumerate(tutti[:5]):
        log.info(f"  {i+1}. {e['titolo'][:50]}... data={e.get('data')}, raw={e.get('data_raw', '')[:30]}")
    
    # Conta quanti eventi hanno una data valida
    con_data = sum(1 for e in tutti if e.get('data'))
    log.info(f"Eventi con data valida: {con_data}/{len(tutti)}")
    
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
    target_str = target.isoformat()
    filtrati = [e for e in eventi if e.get("data") == target_str]
    log.info(f"Filtro per data {target_str}: {len(filtrati)} eventi su {len(eventi)} totali")
    
    # DEBUG: mostra prime 10 date presenti negli eventi
    date_presenti = {}
    for e in eventi:
        if e.get("data"):
            date_presenti[e["data"]] = date_presenti.get(e["data"], 0) + 1
    
    if date_presenti:
        log.info(f"Date presenti nel cache (prime 5): {list(date_presenti.items())[:5]}")
    
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
        "• /aggiorna — forza aggiornamento (admin)\n"
        "• /svuota_cache — svuota cache e ricarica (admin)\n"
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


async def cmd_svuota_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Svuota la cache e ricarica gli eventi"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            await update.message.reply_text("🗑️ Cache svuotata! Ricarico gli eventi...")
            eventi = get_eventi(force=True)
            await update.message.reply_text(f"✅ Ricaricati {len(eventi)} eventi!")
        else:
            await update.message.reply_text("ℹ️ Cache già vuota. Ricarico...")
            eventi = get_eventi(force=True)
            await update.message.reply_text(f"✅ Ricaricati {len(eventi)} eventi!")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Non capisco 🤔 Prova con /oggi, /domani, /weekend o /cerca jazz"
    )


# --------------------------------------------------------------------------- #
# Digest mattutino (inviato da cron, non dal polling)
# --------------------------------------------------------------------------- #

async def invia_digest():
    """Invia il digest giornaliero all'admin via Telegram."""
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
    if FORCE_SCRAPE:
        log.warning("⚠️ FORCE_SCRAPE attivo - la cache verrà ignorata!")
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oggi", cmd_oggi))
    app.add_handler(CommandHandler("domani", cmd_domani))
    app.add_handler(CommandHandler("weekend", cmd_weekend))
    app.add_handler(CommandHandler("cerca", cmd_cerca))
    app.add_handler(CommandHandler("aggiorna", cmd_aggiorna))
    app.add_handler(CommandHandler("svuota_cache", cmd_svuota_cache))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sconosciuto))
    app.run_polling()


if __name__ == "__main__":
    main()
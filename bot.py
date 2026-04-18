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

def carica_cache(filtro: str = None) -> list[dict]:
    """Carica la cache, eventualmente specifica per filtro"""
    cache_key = CACHE_FILE if not filtro else Path(f"eventi_cache_{filtro}.json")
    if not cache_key.exists():
        return []
    try:
        data = json.loads(cache_key.read_text(encoding="utf-8"))
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


def salva_cache(eventi: list[dict], filtro: str = None):
    """Salva la cache, eventualmente specifica per filtro"""
    cache_key = CACHE_FILE if not filtro else Path(f"eventi_cache_{filtro}.json")
    cache_key.write_text(
        json.dumps({"generato_il": datetime.now().isoformat(), "eventi": eventi},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Salvati {len(eventi)} eventi in cache ({filtro or 'generale'})")


def get_eventi(filtro: str = None, force: bool = False) -> list[dict]:
    """
    Ottiene eventi usando i filtri di GenovaToday
    Filtri: "oggi", "domani", "weekend", "settimana", "prossima_settimana", "mese"
    """
    if FORCE_SCRAPE:
        log.info("⚠️ FORCE_SCRAPE attivo - ignoro la cache")
        force = True
    
    if not force:
        cached = carica_cache(filtro)
        if cached:
            return cached
    
    log.info(f"Avvio scraping con filtro: {filtro or 'nessuno'}...")
    
    eventi = []
    
    # Scraping GenovaToday con filtro
    if filtro:
        eventi_genova = scrape_genovatoday(filtro=filtro)
    else:
        eventi_genova = scrape_genovatoday()
    
    eventi.extend(eventi_genova)
    
    # Scraping MenteLocale (sempre completo, poi filtriamo)
    eventi.extend(scrape_mentelocale())
    
    eventi = deduplica(eventi)
    eventi.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    log.info(f"Primi 3 eventi scrapati:")
    for i, e in enumerate(eventi[:3]):
        log.info(f"  {i+1}. {e['titolo'][:50]}... data={e.get('data')}")
    
    salva_cache(eventi, filtro)
    log.info(f"Scraping completato: {len(eventi)} eventi")
    return eventi


# --------------------------------------------------------------------------- #
# Formattazione messaggi
# --------------------------------------------------------------------------- #

def fmt_evento(e: dict, num: int | None = None) -> str:
    righe = []
    if num:
        righe.append(f"*{num}. {e['titolo']}*")
    else:
        righe.append(f"*{e['titolo']}*")

    # Gestione data con intervallo per MenteLocale
    data_inizio = e.get('data_inizio') or e.get('data')
    data_fine = e.get('data_fine')
    
    if data_inizio and data_fine:
        try:
            d_inizio = date.fromisoformat(data_inizio)
            d_fine = date.fromisoformat(data_fine)
            if d_inizio.month == d_fine.month and d_inizio.year == d_fine.year:
                righe.append(f"📅 Dal {d_inizio.day} al {d_fine.day} {d_inizio.strftime('%B').capitalize()} {d_inizio.year}")
            else:
                righe.append(f"📅 Dal {d_inizio.strftime('%d/%m/%Y')} al {d_fine.strftime('%d/%m/%Y')}")
        except ValueError:
            righe.append(f"📅 Dal {data_inizio} al {data_fine}")
    elif data_inizio:
        try:
            d = date.fromisoformat(data_inizio)
            oggi = date.today()
            if d < oggi:
                righe.append(f"📅 Iniziato il {d.strftime('%d/%m/%Y')} (in corso)")
            elif d == oggi:
                righe.append(f"📅 Oggi, {d.strftime('%d/%m/%Y')}")
            else:
                righe.append(f"📅 {d.strftime('%A %d %B').capitalize()} {d.year}")
        except ValueError:
            righe.append(f"📅 {data_inizio}")
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
    eventi = get_eventi(filtro="oggi")
    oggi = date.today()
    testo = invia_lista(eventi, f"🗓 *Eventi oggi — {oggi.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di domani...")
    eventi = get_eventi(filtro="domani")
    domani = date.today() + timedelta(days=1)
    testo = invia_lista(eventi, f"🗓 *Eventi domani — {domani.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi del weekend...")
    eventi = get_eventi(filtro="weekend")
    oggi = date.today()
    giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
    sabato = oggi + timedelta(days=giorni_a_sab)
    domenica = sabato + timedelta(days=1)
    testo = invia_lista(eventi, f"🎉 *Eventi del weekend ({sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*")
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
    
    # Forza aggiornamento per tutti i filtri
    for filtro in ["oggi", "domani", "weekend", None]:
        eventi = get_eventi(filtro=filtro, force=True)
    
    await update.message.reply_text(f"✅ Aggiornato! Ora puoi usare /oggi, /domani, /weekend.")


async def cmd_svuota_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Svuota la cache e ricarica gli eventi"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    try:
        # Cancella tutti i file di cache
        cache_files = list(Path(".").glob("eventi_cache*.json"))
        for f in cache_files:
            f.unlink()
            log.info(f"Cancellato {f}")
        
        await update.message.reply_text("🗑️ Cache svuotata! Ricarico gli eventi...")
        
        # Ricarica tutti i filtri
        for filtro in ["oggi", "domani", "weekend", None]:
            eventi = get_eventi(filtro=filtro, force=True)
        
        await update.message.reply_text(f"✅ Cache ricaricata con successo!")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


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
    
    eventi_oggi = get_eventi(filtro="oggi")
    eventi_domani = get_eventi(filtro="domani")
    eventi_weekend = get_eventi(filtro="weekend")

    testo = (
        f"☀️ *Buongiorno! Digest eventi Genova — {date.today().strftime('%d/%m/%Y')}*\n\n"
        f"📌 *Oggi ({len(eventi_oggi)} eventi)*\n"
    )

    for e in eventi_oggi[:5]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not eventi_oggi:
        testo += "_Nessun evento_\n"

    testo += f"\n📌 *Domani ({len(eventi_domani)} eventi)*\n"
    for e in eventi_domani[:3]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not eventi_domani:
        testo += "_Nessun evento_\n"
    
    if eventi_weekend:
        testo += f"\n🎉 *Weekend: {len(eventi_weekend)} eventi in programma!*\n"

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
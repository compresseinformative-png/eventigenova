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

from scraper import scrape_genovatoday

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CACHE_DIR = Path("cache")
CACHE_MAX_AGE_ORE = 6

# Crea la cartella cache se non esiste
CACHE_DIR.mkdir(exist_ok=True)

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

def get_cache_file(filtro: str) -> Path:
    """Restituisce il percorso del file di cache per un filtro"""
    return CACHE_DIR / f"eventi_{filtro}.json"


def carica_cache(filtro: str) -> list[dict]:
    """Carica la cache per un filtro specifico"""
    cache_file = get_cache_file(filtro)
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        generato = datetime.fromisoformat(data["generato_il"])
        eta = (datetime.now() - generato).total_seconds() / 3600
        if eta < CACHE_MAX_AGE_ORE:
            log.info(f"Cache valida per '{filtro}' ({eta:.1f}h fa), {len(data['eventi'])} eventi")
            return data["eventi"]
        else:
            log.info(f"Cache scaduta per '{filtro}' ({eta:.1f}h fa)")
    except Exception as e:
        log.warning(f"Cache corrotta per '{filtro}': {e}")
    return []


def salva_cache(filtro: str, eventi: list[dict]):
    """Salva la cache per un filtro specifico"""
    cache_file = get_cache_file(filtro)
    cache_file.write_text(
        json.dumps({
            "generato_il": datetime.now().isoformat(),
            "filtro": filtro,
            "totale": len(eventi),
            "eventi": eventi
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Salvati {len(eventi)} eventi in cache per '{filtro}'")


def get_eventi(filtro: str, force: bool = False) -> list[dict]:
    """
    Ottiene eventi per un filtro specifico
    Filtri: "oggi", "domani", "weekend"
    """
    if FORCE_SCRAPE:
        log.info("⚠️ FORCE_SCRAPE attivo - ignoro la cache")
        force = True
    
    if not force:
        cached = carica_cache(filtro)
        if cached:
            return cached
    
    log.info(f"Avvio scraping per '{filtro}'...")
    eventi = scrape_genovatoday(filtro=filtro)
    
    # Ordina per data (più recenti prima)
    eventi.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    salva_cache(filtro, eventi)
    log.info(f"Scraping completato: {len(eventi)} eventi per '{filtro}'")
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

    if e.get("data"):
        try:
            d = date.fromisoformat(e["data"])
            oggi = date.today()
            if d == oggi:
                righe.append(f"📅 OGGI")
            elif d == oggi + timedelta(days=1):
                righe.append(f"📅 DOMANI")
            else:
                righe.append(f"📅 {d.strftime('%A %d %B %Y').capitalize()}")
        except ValueError:
            righe.append(f"📅 {e.get('data_raw', '')}")
    elif e.get("data_raw"):
        righe.append(f"📅 {e['data_raw']}")

    if e.get("luogo") and e["luogo"] != "Genova":
        righe.append(f"📍 {e['luogo']}")

    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")

    return "\n".join(righe)


def invia_lista(eventi: list[dict], intestazione: str) -> str:
    if not eventi:
        return f"{intestazione}\n\n_Nessun evento trovato_ 😔"

    parti = [intestazione + "\n"]
    for i, e in enumerate(eventi[:15], 1):  # Max 15 eventi per messaggio
        parti.append(fmt_evento(e, i))
        parti.append("—" * 20)

    if len(eventi) > 15:
        parti.append(f"_...e altri {len(eventi) - 15} eventi. Usa /cerca per filtrare._")

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
        "\n_Fonte: GenovaToday_"
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


async def cmd_oggi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di oggi...")
    eventi = get_eventi("oggi")
    oggi = date.today()
    testo = invia_lista(eventi, f"🗓 *Eventi OGGI — {oggi.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di domani...")
    eventi = get_eventi("domani")
    domani = date.today() + timedelta(days=1)
    testo = invia_lista(eventi, f"🗓 *Eventi DOMANI — {domani.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi del weekend...")
    eventi = get_eventi("weekend")
    oggi = date.today()
    giorni_a_sab = (5 - oggi.weekday()) % 7
    if giorni_a_sab == 0:
        giorni_a_sab = 7
    sabato = oggi + timedelta(days=giorni_a_sab)
    domenica = sabato + timedelta(days=1)
    testo = invia_lista(eventi, f"🎉 *Eventi WEEKEND ({sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_cerca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args).strip().lower()
    if not query:
        await update.message.reply_text(
            "Uso: /cerca \\[parola chiave\\]\nEsempio: /cerca jazz\n\n"
            "Cerca tra gli eventi di oggi, domani e weekend.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(f"⏳ Cerco \"{query}\" tra gli eventi...")
    
    # Cerca in tutti gli eventi (oggi, domani, weekend)
    tutti_eventi = []
    for filtro in ["oggi", "domani", "weekend"]:
        eventi = get_eventi(filtro)
        tutti_eventi.extend(eventi)
    
    # Deduplica per titolo
    visti = set()
    eventi_unici = []
    for e in tutti_eventi:
        if e["titolo"] not in visti:
            visti.add(e["titolo"])
            eventi_unici.append(e)
    
    # Filtra per parola chiave
    filtrati = [
        e for e in eventi_unici
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
    for filtro in ["oggi", "domani", "weekend"]:
        eventi = get_eventi(filtro, force=True)
        log.info(f"Aggiornato {filtro}: {len(eventi)} eventi")
    
    await update.message.reply_text(f"✅ Aggiornamento completato! Usa /oggi, /domani o /weekend.")


async def cmd_svuota_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Svuota la cache e ricarica gli eventi"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    try:
        # Cancella tutti i file di cache
        cache_files = list(CACHE_DIR.glob("eventi_*.json"))
        cancellati = 0
        for f in cache_files:
            f.unlink()
            cancellati += 1
        
        await update.message.reply_text(f"🗑️ Cache svuotata ({cancellati} file). Ricarico gli eventi...")
        
        # Ricarica tutti i filtri
        for filtro in ["oggi", "domani", "weekend"]:
            eventi = get_eventi(filtro, force=True)
            log.info(f"Ricaricato {filtro}: {len(eventi)} eventi")
        
        await update.message.reply_text(f"✅ Cache ricaricata con successo!")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Non capisco 🤔 Prova con:\n"
        "/oggi - eventi di oggi\n"
        "/domani - eventi di domani\n"
        "/weekend - eventi del weekend\n"
        "/cerca [parola] - cerca un evento"
    )


# --------------------------------------------------------------------------- #
# Digest mattutino
# --------------------------------------------------------------------------- #

async def invia_digest():
    """Invia il digest giornaliero all'admin via Telegram."""
    from telegram import Bot
    bot = Bot(token=TOKEN)
    
    eventi_oggi = get_eventi("oggi")
    eventi_domani = get_eventi("domani")

    testo = (
        f"☀️ *Buongiorno! Digest eventi Genova — {date.today().strftime('%d/%m/%Y')}*\n\n"
        f"📌 *OGGI ({len(eventi_oggi)} eventi)*\n"
    )

    for e in eventi_oggi[:5]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not eventi_oggi:
        testo += "_Nessun evento_\n"

    testo += f"\n📌 *DOMANI ({len(eventi_domani)} eventi)*\n"
    for e in eventi_domani[:3]:
        testo += f"• {e['titolo']} — {e.get('luogo', 'Genova')}\n"
    if not eventi_domani:
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
"""
Bot Telegram — Aggregatore eventi Genova
========================================

Comandi disponibili:
  /oggi              → eventi di oggi
  /domani            → eventi di domani
  /weekend           → eventi del weekend in corso
  /data 01/05/2026   → eventi di una data specifica
  /cerca jazz        → cerca eventi per parola chiave
  /aggiorna          → forza un nuovo scraping (solo admin)
  /svuota_cache      → svuota la cache e ricarica (solo admin)

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

from scraper import scrape_genovatoday, parse_data_input

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CACHE_DIR = Path("cache")
CACHE_MAX_AGE_ORE = 6

CACHE_DIR.mkdir(exist_ok=True)

FORCE_SCRAPE = os.environ.get("FORCE_SCRAPE", "false").lower() == "true"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def get_cache_key(filtro: str = None, data_inizio: str = None, data_fine: str = None) -> str:
    if filtro:
        return f"eventi_{filtro}.json"
    elif data_inizio and data_fine:
        return f"eventi_{data_inizio}_{data_fine}.json"
    return None


def carica_cache(key: str) -> list[dict]:
    cache_file = CACHE_DIR / key
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        generato = datetime.fromisoformat(data["generato_il"])
        eta = (datetime.now() - generato).total_seconds() / 3600
        if eta < CACHE_MAX_AGE_ORE:
            log.info(f"Cache valida per '{key}' ({eta:.1f}h fa), {len(data['eventi'])} eventi")
            return data["eventi"]
    except Exception as e:
        log.warning(f"Cache corrotta: {e}")
    return []


def salva_cache(key: str, eventi: list[dict]):
    cache_file = CACHE_DIR / key
    cache_file.write_text(
        json.dumps({
            "generato_il": datetime.now().isoformat(),
            "key": key,
            "totale": len(eventi),
            "eventi": eventi
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Salvati {len(eventi)} eventi in cache per '{key}'")


def get_eventi(filtro: str = None, data_inizio: date = None, data_fine: date = None, force: bool = False) -> list[dict]:
    if FORCE_SCRAPE:
        force = True
    
    key = None
    if filtro:
        key = get_cache_key(filtro=filtro)
    elif data_inizio and data_fine:
        key = get_cache_key(data_inizio=data_inizio.isoformat(), data_fine=data_fine.isoformat())
    
    if not force and key:
        cached = carica_cache(key)
        if cached:
            return cached
    
    log.info(f"Avvio scraping...")
    
    if filtro:
        eventi = scrape_genovatoday(filtro=filtro)
    elif data_inizio and data_fine:
        eventi = scrape_genovatoday(data_inizio=data_inizio, data_fine=data_fine)
    else:
        return []
    
    if key:
        salva_cache(key, eventi)
    
    log.info(f"Scraping completato: {len(eventi)} eventi")
    return eventi


# --------------------------------------------------------------------------- #
# Formattazione messaggi
# --------------------------------------------------------------------------- #

def fmt_evento(e: dict, num: int) -> str:
    righe = [f"*{num}. {e['titolo']}*"]
    
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


async def invia_lista(update_or_bot, eventi: list[dict], intestazione: str, is_digest: bool = False):
    """Invia gli eventi in più messaggi, 15 per volta"""
    if not eventi:
        if is_digest:
            log.info(f"Digest: nessun evento per {intestazione}")
        else:
            await update_or_bot.message.reply_text(f"{intestazione}\n\n_Nessun evento trovato_ 😔")
        return
    
    if is_digest:
        # Per i digest, usa il bot direttamente
        bot = update_or_bot
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=intestazione)
        
        blocco_size = 15
        for i in range(0, len(eventi), blocco_size):
            blocco = eventi[i:i+blocco_size]
            messaggio = ""
            for idx, e in enumerate(blocco, start=i+1):
                messaggio += fmt_evento(e, idx) + "\n\n" + "—" * 20 + "\n\n"
            if messaggio:
                await bot.send_message(chat_id=ADMIN_CHAT_ID, text=messaggio, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        # Per i comandi interattivi
        await update_or_bot.message.reply_text(intestazione)
        
        blocco_size = 15
        for i in range(0, len(eventi), blocco_size):
            blocco = eventi[i:i+blocco_size]
            messaggio = ""
            for idx, e in enumerate(blocco, start=i+1):
                messaggio += fmt_evento(e, idx) + "\n\n" + "—" * 20 + "\n\n"
            if messaggio:
                await update_or_bot.message.reply_text(messaggio, parse_mode="Markdown", disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
# Handler comandi
# --------------------------------------------------------------------------- #

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    testo = (
        "👋 *Benvenuto nell'aggregatore eventi di Genova!*\n\n"
        "Comandi disponibili:\n"
        "• /oggi — eventi di oggi\n"
        "• /domani — eventi di domani\n"
        "• /weekend — eventi del weekend in corso\n"
        "• /data 01/05/2026 — eventi di una data specifica\n"
        "• /cerca jazz — cerca eventi per parola chiave\n"
        "• /aggiorna — forza aggiornamento (admin)\n"
        "• /svuota_cache — svuota cache e ricarica (admin)\n"
        "\n_Fonte: GenovaToday_"
    )
    await update.message.reply_text(testo, parse_mode="Markdown")


async def cmd_oggi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di oggi...")
    eventi = get_eventi(filtro="oggi")
    oggi = date.today()
    await invia_lista(update, eventi, f"🗓 *EVENTI OGGI — {oggi.strftime('%d/%m/%Y')}*\n")


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di domani...")
    eventi = get_eventi(filtro="domani")
    domani = date.today() + timedelta(days=1)
    await invia_lista(update, eventi, f"🗓 *EVENTI DOMANI — {domani.strftime('%d/%m/%Y')}*\n")


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi del weekend in corso...")
    eventi = get_eventi(filtro="weekend")
    
    oggi = date.today()
    if oggi.weekday() == 5:
        sabato = oggi
        domenica = oggi + timedelta(days=1)
    elif oggi.weekday() == 6:
        sabato = oggi - timedelta(days=1)
        domenica = oggi
    else:
        sabato = oggi - timedelta(days=oggi.weekday() + 2)
        domenica = sabato + timedelta(days=1)
    
    await invia_lista(update, eventi, f"🎉 *EVENTI WEEKEND ({sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*\n")


async def cmd_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Uso: /data DD/MM/YYYY\nEsempio: /data 01/05/2026",
            parse_mode="Markdown"
        )
        return
    
    data_str = " ".join(ctx.args).strip()
    data_target = parse_data_input(data_str)
    
    if not data_target:
        await update.message.reply_text(
            f"❌ Formato data non valido. Usa DD/MM/YYYY\nEsempio: /data 01/05/2026"
        )
        return
    
    await update.message.reply_text(f"⏳ Cerco gli eventi del {data_target.strftime('%d/%m/%Y')}...")
    eventi = get_eventi(data_inizio=data_target, data_fine=data_target)
    
    await invia_lista(update, eventi, f"📅 *EVENTI DEL {data_target.strftime('%d/%m/%Y')}*\n")


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
    
    tutti_eventi = []
    for filtro in ["oggi", "domani", "weekend"]:
        eventi = get_eventi(filtro=filtro)
        tutti_eventi.extend(eventi)
    
    visti = set()
    eventi_unici = []
    for e in tutti_eventi:
        if e["titolo"] not in visti:
            visti.add(e["titolo"])
            eventi_unici.append(e)
    
    filtrati = [
        e for e in eventi_unici
        if query in e.get("titolo", "").lower()
        or query in e.get("luogo", "").lower()
    ]
    
    await invia_lista(update, filtrati, f"🔍 *RISULTATI PER \"{query.upper()}\"*\n")


async def cmd_aggiorna(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    await update.message.reply_text("⏳ Aggiornamento in corso...")
    
    for filtro in ["oggi", "domani", "weekend"]:
        eventi = get_eventi(filtro=filtro, force=True)
        log.info(f"Aggiornato {filtro}: {len(eventi)} eventi")
    
    await update.message.reply_text(f"✅ Aggiornamento completato!")


async def cmd_svuota_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    try:
        cache_files = list(CACHE_DIR.glob("eventi_*.json"))
        cancellati = 0
        for f in cache_files:
            f.unlink()
            cancellati += 1
        
        await update.message.reply_text(f"🗑️ Cache svuotata ({cancellati} file). Ricarico...")
        
        for filtro in ["oggi", "domani", "weekend"]:
            eventi = get_eventi(filtro=filtro, force=True)
        
        await update.message.reply_text(f"✅ Cache ricaricata!")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Non capisco 🤔 Prova con:\n"
        "/oggi - eventi di oggi\n"
        "/domani - eventi di domani\n"
        "/weekend - eventi del weekend\n"
        "/data 01/05/2026 - eventi di una data\n"
        "/cerca [parola] - cerca un evento"
    )


# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #

async def invia_digest_settimana():
    """Invia il digest della settimana successiva (domenica alle 20:00)"""
    from telegram import Bot
    bot = Bot(token=TOKEN)
    
    oggi = date.today()
    # Calcola il lunedì della settimana successiva
    giorni_a_lunedi = (7 - oggi.weekday()) % 7
    if giorni_a_lunedi == 0:
        giorni_a_lunedi = 7
    lunedi = oggi + timedelta(days=giorni_a_lunedi)
    domenica = lunedi + timedelta(days=6)
    
    log.info(f"Digest settimanale: {lunedi.strftime('%d/%m/%Y')} - {domenica.strftime('%d/%m/%Y')}")
    
    # Raccogli eventi per ogni giorno della settimana
    tutti_eventi = []
    giorno_corrente = lunedi
    while giorno_corrente <= domenica:
        eventi = get_eventi(data_inizio=giorno_corrente, data_fine=giorno_corrente)
        for e in eventi:
            e["giorno_display"] = giorno_corrente.strftime("%A %d/%m").capitalize()
        tutti_eventi.extend(eventi)
        giorno_corrente += timedelta(days=1)
    
    if not tutti_eventi:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📅 *Digest settimanale ({lunedi.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*\n\n_Nessun evento trovato per la prossima settimana_ 😔", parse_mode="Markdown")
        return
    
    # Raggruppa per giorno
    eventi_per_giorno = {}
    for e in tutti_eventi:
        giorno = e.get("giorno_display", "Data sconosciuta")
        if giorno not in eventi_per_giorno:
            eventi_per_giorno[giorno] = []
        eventi_per_giorno[giorno].append(e)
    
    # Invia un messaggio per ogni giorno
    for giorno, eventi in eventi_per_giorno.items():
        intestazione = f"📅 *{giorno.upper()}*"
        await invia_lista(bot, eventi, intestazione, is_digest=True)
    
    log.info(f"Digest settimanale inviato: {len(tutti_eventi)} eventi totali")


async def invia_digest_weekend():
    """Invia il digest del weekend (venerdì alle 09:00)"""
    from telegram import Bot
    bot = Bot(token=TOKEN)
    
    oggi = date.today()
    # Calcola il weekend di questa settimana (sabato e domenica)
    giorni_a_sabato = (5 - oggi.weekday()) % 7
    if giorni_a_sabato == 0:
        giorni_a_sabato = 7
    sabato = oggi + timedelta(days=giorni_a_sabato)
    domenica = sabato + timedelta(days=1)
    
    log.info(f"Digest weekend: {sabato.strftime('%d/%m/%Y')} - {domenica.strftime('%d/%m/%Y')}")
    
    eventi = get_eventi(data_inizio=sabato, data_fine=domenica)
    
    intestazione = f"🎉 *WEEKEND ({sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*\n"
    await invia_lista(bot, eventi, intestazione, is_digest=True)
    
    log.info(f"Digest weekend inviato: {len(eventi)} eventi")


# --------------------------------------------------------------------------- #
# Avvio
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", choices=["weekly", "weekend"], default=None,
                        help="Invia digest: weekly (domenica) o weekend (venerdì)")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("Errore: variabile TOKEN non impostata")

    if args.digest == "weekly":
        import asyncio
        asyncio.run(invia_digest_settimana())
        return
    elif args.digest == "weekend":
        import asyncio
        asyncio.run(invia_digest_weekend())
        return

    log.info("Bot avviato, in ascolto...")
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oggi", cmd_oggi))
    app.add_handler(CommandHandler("domani", cmd_domani))
    app.add_handler(CommandHandler("weekend", cmd_weekend))
    app.add_handler(CommandHandler("data", cmd_data))
    app.add_handler(CommandHandler("cerca", cmd_cerca))
    app.add_handler(CommandHandler("aggiorna", cmd_aggiorna))
    app.add_handler(CommandHandler("svuota_cache", cmd_svuota_cache))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sconosciuto))
    app.run_polling()


if __name__ == "__main__":
    main()
"""
Bot Telegram — Aggregatore eventi Genova
========================================

Comandi disponibili:
  /oggi              → eventi di oggi
  /domani            → eventi di domani
  /weekend           → eventi del weekend
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

from scraper import scrape_mentelocale, converti_data_italiana

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

def get_cache_key(filtro: str = None, data: str = None) -> str:
    if filtro:
        return f"eventi_{filtro}.json"
    elif data:
        return f"eventi_data_{data}.json"
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


def get_eventi(filtro: str = None, data_target: date = None, force: bool = False) -> list[dict]:
    if FORCE_SCRAPE:
        force = True
    
    key = None
    if filtro:
        key = get_cache_key(filtro=filtro)
    elif data_target:
        key = get_cache_key(data=data_target.isoformat())
    
    if not force and key:
        cached = carica_cache(key)
        if cached:
            return cached
    
    log.info(f"Avvio scraping...")
    
    if filtro:
        eventi = scrape_mentelocale(filtro=filtro)
    elif data_target:
        eventi = scrape_mentelocale(data_target=data_target)
    else:
        return []
    
    if key:
        salva_cache(key, eventi)
    
    log.info(f"Scraping completato: {len(eventi)} eventi")
    return eventi


# --------------------------------------------------------------------------- #
# Formattazione messaggi
# --------------------------------------------------------------------------- #

def fmt_evento_con_immagine(e: dict, num: int) -> str:
    """Formatta un evento con immagine (per i primi 10)"""
    righe = []
    
    # Aggiungi l'immagine se presente
    if e.get("immagine"):
        righe.append(f"![Immagine]({e['immagine']})")
    
    righe.append(f"*{num}. {e['titolo']}*")
    
    # Data
    if e.get("data_inizio") and e.get("data_fine"):
        righe.append(f"📅 Dal {e['data_inizio'].replace('-', '/')} al {e['data_fine'].replace('-', '/')}")
    elif e.get("data_inizio"):
        righe.append(f"📅 {e['data_inizio'].replace('-', '/')}")
    elif e.get("data_raw"):
        righe.append(f"📅 {e['data_raw']}")
    
    if e.get("luogo"):
        righe.append(f"📍 {e['luogo']}")
    
    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")
    
    righe.append(f"🏷️ {e['fonte']}")
    
    return "\n".join(righe)


def fmt_evento_semplice(e: dict, num: int) -> str:
    """Formatta un evento senza immagine (per gli altri)"""
    righe = [f"*{num}. {e['titolo']}*"]
    
    if e.get("data_inizio") and e.get("data_fine"):
        righe.append(f"📅 Dal {e['data_inizio'].replace('-', '/')} al {e['data_fine'].replace('-', '/')}")
    elif e.get("data_inizio"):
        righe.append(f"📅 {e['data_inizio'].replace('-', '/')}")
    elif e.get("data_raw"):
        righe.append(f"📅 {e['data_raw']}")
    
    if e.get("luogo"):
        righe.append(f"📍 {e['luogo']}")
    
    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")
    
    return "\n".join(righe)


async def invia_lista(update_or_bot, eventi: list[dict], intestazione: str, is_digest: bool = False):
    """Invia gli eventi: primi 10 con immagine, gli altri semplici"""
    if not eventi:
        if is_digest:
            log.info(f"Digest: nessun evento per {intestazione}")
        else:
            await update_or_bot.message.reply_text(f"{intestazione}\n\n_Nessun evento trovato_ 😔")
        return
    
    # Messaggio di intestazione
    if is_digest:
        bot = update_or_bot
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=intestazione)
        send_func = lambda msg: bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update_or_bot.message.reply_text(intestazione)
        send_func = lambda msg: update_or_bot.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
    
    # Primi 10 con immagine (uno per messaggio)
    for i, e in enumerate(eventi[:10], 1):
        messaggio = fmt_evento_con_immagine(e, i)
        await send_func(messaggio)
    
    # Eventuali altri eventi (dal 11 in poi) in blocchi da 15
    if len(eventi) > 10:
        rimanenti = eventi[10:]
        blocco_size = 15
        for i in range(0, len(rimanenti), blocco_size):
            blocco = rimanenti[i:i+blocco_size]
            messaggio = ""
            for idx, e in enumerate(blocco, start=11+i):
                messaggio += fmt_evento_semplice(e, idx) + "\n\n" + "—" * 20 + "\n\n"
            if messaggio:
                await send_func(messaggio)


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
        "• /data 01/05/2026 — eventi di una data specifica\n"
        "• /cerca jazz — cerca eventi per parola chiave\n"
        "• /aggiorna — forza aggiornamento (admin)\n"
        "• /svuota_cache — svuota cache e ricarica (admin)\n"
        "\n_Fonte: Mentelocale_"
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
    await update.message.reply_text("⏳ Cerco gli eventi del weekend...")
    eventi = get_eventi(filtro="weekend")
    await invia_lista(update, eventi, f"🎉 *EVENTI WEEKEND*\n")


async def cmd_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Uso: /data DD/MM/YYYY\nEsempio: /data 01/05/2026",
            parse_mode="Markdown"
        )
        return
    
    data_str = " ".join(ctx.args).strip()
    
    # Converte DD/MM/YYYY in oggetto date
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", data_str)
    if not m:
        await update.message.reply_text(
            f"❌ Formato data non valido. Usa DD/MM/YYYY\nEsempio: /data 01/05/2026"
        )
        return
    
    g, mese, anno = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        data_target = date(anno, mese, g)
    except ValueError:
        await update.message.reply_text(f"❌ Data non valida: {data_str}")
        return
    
    await update.message.reply_text(f"⏳ Cerco gli eventi del {data_target.strftime('%d/%m/%Y')}...")
    eventi = get_eventi(data_target=data_target)
    
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
    from telegram import Bot
    bot = Bot(token=TOKEN)
    
    eventi_oggi = get_eventi(filtro="oggi")
    eventi_domani = get_eventi(filtro="domani")
    eventi_weekend = get_eventi(filtro="weekend")

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
    
    if eventi_weekend:
        testo += f"\n🎉 *WEEKEND: {len(eventi_weekend)} eventi in programma!*\n"

    testo += "\n_Scrivi /oggi o /weekend per i dettagli._"

    await bot.send_message(chat_id=ADMIN_CHAT_ID, text=testo, parse_mode="Markdown")
    log.info("Digest inviato")


# --------------------------------------------------------------------------- #
# Avvio
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--digest", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("Errore: variabile TOKEN non impostata")

    if args.digest:
        import asyncio
        asyncio.run(invia_digest_settimana())
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
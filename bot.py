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
    cache_key = Path(f"eventi_cache_{filtro}.json") if filtro else CACHE_FILE
    if not cache_key.exists():
        return []
    try:
        data = json.loads(cache_key.read_text(encoding="utf-8"))
        generato = datetime.fromisoformat(data["generato_il"])
        età = (datetime.now() - generato).total_seconds() / 3600
        if età < CACHE_MAX_AGE_ORE:
            log.info(f"Cache valida ({età:.1f}h fa), {len(data['eventi'])} eventi")
            return data["eventi"]
    except Exception as e:
        log.warning(f"Cache corrotta: {e}")
    return []


def salva_cache(eventi: list[dict], filtro: str = None):
    cache_key = Path(f"eventi_cache_{filtro}.json") if filtro else CACHE_FILE
    cache_key.write_text(
        json.dumps({"generato_il": datetime.now().isoformat(), "eventi": eventi},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Salvati {len(eventi)} eventi in cache ({filtro or 'generale'})")


def get_eventi_per_filtro(filtro: str, force: bool = False) -> list[dict]:
    """Ottiene eventi per un filtro specifico (oggi, domani, weekend)"""
    if FORCE_SCRAPE:
        force = True
    
    if not force:
        cached = carica_cache(filtro)
        if cached:
            return cached
    
    log.info(f"Avvio scraping per filtro: {filtro}")
    eventi = []
    
    # GenovaToday con filtro
    eventi.extend(scrape_genovatoday(filtro=filtro))
    
    # MenteLocale per le date specifiche
    oggi = date.today()
    if filtro == "oggi":
        eventi.extend(scrape_mentelocale(oggi))
    elif filtro == "domani":
        eventi.extend(scrape_mentelocale(oggi + timedelta(days=1)))
    elif filtro == "weekend":
        giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
        sabato = oggi + timedelta(days=giorni_a_sab)
        domenica = sabato + timedelta(days=1)
        eventi.extend(scrape_mentelocale(sabato))
        eventi.extend(scrape_mentelocale(domenica))
    
    eventi = deduplica(eventi)
    eventi.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    salva_cache(eventi, filtro)
    log.info(f"Scraping completato: {len(eventi)} eventi per {filtro}")
    return eventi


# --------------------------------------------------------------------------- #
# Formattazione
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
    else:
        righe.append(f"📅 Data non specificata")

    if e.get("luogo") and e["luogo"] != "Genova":
        righe.append(f"📍 {e['luogo']}")

    if e.get("url"):
        righe.append(f"[→ Dettagli]({e['url']})")

    fonte = e.get("fonte", "")
    righe.append(f"_Fonte: {fonte}_")

    return "\n".join(righe)


def invia_lista(eventi: list[dict], intestazione: str) -> str:
    if not eventi:
        return f"{intestazione}\n\n_Nessun evento trovato_ 😔"

    parti = [intestazione + "\n"]
    for i, e in enumerate(eventi[:10], 1):
        parti.append(fmt_evento(e, i))
        parti.append("—" * 20)

    if len(eventi) > 10:
        parti.append(f"_...e altri {len(eventi) - 10} eventi._")

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
    eventi = get_eventi_per_filtro("oggi")
    oggi = date.today()
    testo = invia_lista(eventi, f"🗓 *Eventi OGGI — {oggi.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi di domani...")
    eventi = get_eventi_per_filtro("domani")
    domani = date.today() + timedelta(days=1)
    testo = invia_lista(eventi, f"🗓 *Eventi DOMANI — {domani.strftime('%d/%m/%Y')}*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco gli eventi del weekend...")
    eventi = get_eventi_per_filtro("weekend")
    oggi = date.today()
    giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
    sabato = oggi + timedelta(days=giorni_a_sab)
    domenica = sabato + timedelta(days=1)
    testo = invia_lista(eventi, f"🎉 *Eventi WEEKEND ({sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')})*")
    await update.message.reply_text(testo, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_cerca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args).strip().lower()
    if not query:
        await update.message.reply_text("Uso: /cerca \\[parola chiave\\]\nEsempio: /cerca jazz", parse_mode="Markdown")
        return

    await update.message.reply_text(f"⏳ Cerco \"{query}\"...")
    
    # Per la ricerca, prendiamo eventi di oggi e domani
    eventi = get_eventi_per_filtro("oggi") + get_eventi_per_filtro("domani")
    eventi = deduplica(eventi)
    
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
    await update.message.reply_text("⏳ Aggiornamento in corso...")
    
    for filtro in ["oggi", "domani", "weekend"]:
        eventi = get_eventi_per_filtro(filtro, force=True)
    
    await update.message.reply_text(f"✅ Aggiornato! Usa /oggi, /domani o /weekend.")


async def cmd_svuota_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Comando riservato all'admin.")
        return
    
    try:
        cache_files = list(Path(".").glob("eventi_cache*.json"))
        for f in cache_files:
            f.unlink()
        
        await update.message.reply_text("🗑️ Cache svuotata! Ricarico...")
        
        for filtro in ["oggi", "domani", "weekend"]:
            eventi = get_eventi_per_filtro(filtro, force=True)
        
        await update.message.reply_text(f"✅ Cache ricaricata con successo!")
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}")


async def msg_sconosciuto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Non capisco 🤔 Prova con /oggi, /domani, /weekend o /cerca jazz"
    )


# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #

async def invia_digest():
    from telegram import Bot
    bot = Bot(token=TOKEN)
    
    eventi_oggi = get_eventi_per_filtro("oggi")
    eventi_domani = get_eventi_per_filtro("domani")

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
    parser.add_argument("--digest", action="store_true")
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
    app.add_handler(CommandHandler("svuota_cache", cmd_svuota_cache))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sconosciuto))
    app.run_polling()


if __name__ == "__main__":
    main()
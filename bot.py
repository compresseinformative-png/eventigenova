import os
import json
import logging
from datetime import date
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scraper import scrape_mentelocale

TOKEN = os.environ.get("TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def get_eventi(filtro):
    """Scraping diretto senza cache"""
    log.info(f"Scraping {filtro}...")
    return scrape_mentelocale(filtro)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Eventi Genova*\n\n"
        "/oggi - eventi di oggi\n"
        "/domani - eventi di domani\n"
        "/weekend - eventi del weekend\n"
        "/cerca parola - cerca evento\n\n"
        "_Fonte: Mentelocale_",
        parse_mode="Markdown"
    )

async def cmd_oggi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("oggi")
    
    if not eventi:
        await update.message.reply_text("Nessun evento trovato per oggi 😔")
        return
    
    oggi = date.today().strftime("%d/%m/%Y")
    msg = f"🗓 *EVENTI OGGI ({oggi})*\n\n"
    
    for i, e in enumerate(eventi[:15], 1):
        msg += f"{i}. *{e['titolo']}*\n"
        if e.get('data'):
            msg += f"   📅 {e['data']}\n"
        if e.get('url'):
            msg += f"   [→ Dettagli]({e['url']})\n"
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

async def cmd_domani(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("domani")
    
    if not eventi:
        await update.message.reply_text("Nessun evento trovato per domani 😔")
        return
    
    domani = (date.today() + __import__('datetime').timedelta(days=1)).strftime("%d/%m/%Y")
    msg = f"🗓 *EVENTI DOMANI ({domani})*\n\n"
    
    for i, e in enumerate(eventi[:15], 1):
        msg += f"{i}. *{e['titolo']}*\n"
        if e.get('data'):
            msg += f"   📅 {e['data']}\n"
        if e.get('url'):
            msg += f"   [→ Dettagli]({e['url']})\n"
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

async def cmd_weekend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cerco eventi...")
    eventi = get_eventi("weekend")
    
    if not eventi:
        await update.message.reply_text("Nessun evento trovato per il weekend 😔")
        return
    
    msg = f"🎉 *EVENTI WEEKEND*\n\n"
    
    for i, e in enumerate(eventi[:15], 1):
        msg += f"{i}. *{e['titolo']}*\n"
        if e.get('data'):
            msg += f"   📅 {e['data']}\n"
        if e.get('url'):
            msg += f"   [→ Dettagli]({e['url']})\n"
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

async def cmd_cerca(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: /cerca parola")
        return
    
    query = " ".join(ctx.args).lower()
    await update.message.reply_text(f"⏳ Cerco '{query}'...")
    
    tutti = []
    for filtro in ["oggi", "domani", "weekend"]:
        tutti.extend(get_eventi(filtro))
    
    filtrati = [e for e in tutti if query in e['titolo'].lower()]
    
    if not filtrati:
        await update.message.reply_text(f"Nessun evento trovato per '{query}'")
        return
    
    msg = f"🔍 *RISULTATI PER '{query.upper()}'*\n\n"
    for i, e in enumerate(filtrati[:10], 1):
        msg += f"{i}. *{e['titolo']}*\n"
        if e.get('url'):
            msg += f"   [→ Dettagli]({e['url']})\n"
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

async def cmd_aggiorna(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Solo admin")
        return
    
    await update.message.reply_text("⏳ Aggiornamento...")
    # Forza nuovo scraping (senza cache)
    for filtro in ["oggi", "domani", "weekend"]:
        scrape_mentelocale(filtro)
    await update.message.reply_text("✅ Aggiornato!")

def main():
    if not TOKEN:
        raise SystemExit("Errore: TOKEN non impostato")
    
    log.info("Bot avviato")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("oggi", cmd_oggi))
    app.add_handler(CommandHandler("domani", cmd_domani))
    app.add_handler(CommandHandler("weekend", cmd_weekend))
    app.add_handler(CommandHandler("cerca", cmd_cerca))
    app.add_handler(CommandHandler("aggiorna", cmd_aggiorna))
    app.run_polling()

if __name__ == "__main__":
    main()
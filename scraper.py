"""
Aggregatore eventi Genova
Scraper per: genovatoday.it con filtri per data
"""

import requests
import json
import argparse
import re
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def parse_data_it(testo: str) -> str | None:
    """Parsa date in vari formati, restituisce YYYY-MM-DD"""
    if not testo:
        return None
    
    testo = testo.strip()
    
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]\d{2}:\d{2}.*)?", testo)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            pass
    
    return None


def parse_data_input(data_str: str) -> date | None:
    """Parsa una data in input dall'utente (formato DD/MM/YYYY)"""
    if not data_str:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", data_str.strip())
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g)
        except ValueError:
            return None
    return None


def get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  [ERRORE] {url} -> {e}")
        return None

def scrape_genovatoday(filtro: str = None) -> list[dict]:
    """
    GenovaToday con filtro date via URL
    """
    eventi = []
    
    oggi = date.today()
    
    if filtro == "oggi":
        url = f"https://www.genovatoday.it/eventi/dal/{oggi.isoformat()}/al/{oggi.isoformat()}/"
    elif filtro == "domani":
        domani = oggi + timedelta(days=1)
        url = f"https://www.genovatoday.it/eventi/dal/{domani.isoformat()}/al/{domani.isoformat()}/"
    elif filtro == "weekend":
        if oggi.weekday() == 5:
            sabato = oggi
            domenica = oggi + timedelta(days=1)
        elif oggi.weekday() == 6:
            sabato = oggi - timedelta(days=1)
            domenica = oggi
        else:
            sabato = oggi - timedelta(days=oggi.weekday() + 2)
            domenica = sabato + timedelta(days=1)
        
        url = f"https://www.genovatoday.it/eventi/dal/{sabato.isoformat()}/al/{domenica.isoformat()}/"
        print(f"  Weekend: {sabato.strftime('%d/%m')} - {domenica.strftime('%d/%m')}")
    else:
        return eventi
    
    print(f"  -> GenovaToday: {url}")
    soup = get(url)
    if not soup:
        return eventi

    articles = soup.find_all("article")
    
    # DEBUG: stampa quanti articoli trova e i primi titoli
    print(f"  [DEBUG] Trovati {len(articles)} articoli")
    for i, art in enumerate(articles[:5]):
        titolo_el = art.find(["h2", "h3"])
        if titolo_el:
            print(f"  [DEBUG] Articolo {i}: {titolo_el.get_text(strip=True)[:50]}")
    
    # Prendi TUTTI gli articoli per ora (senza saltare)
    for article in articles:
        link_el = article.find("a", href=True)
        titolo_el = article.find(["h2", "h3"])
        
        if not link_el or not titolo_el:
            continue
        
        titolo = titolo_el.get_text(strip=True)
        if not titolo or len(titolo) < 5:
            continue
        
        href = link_el["href"]
        if not href.startswith("http"):
            href = "https://www.genovatoday.it" + href
        
        time_el = article.find("time")
        data_raw = ""
        data_parsata = None
        if time_el:
            data_raw = time_el.get("datetime", "") or time_el.get_text(strip=True)
            data_parsata = parse_data_it(data_raw) if data_raw else None
        
        luogo_el = article.find(class_=re.compile(r"location|place|luogo", re.I))
        luogo = luogo_el.get_text(strip=True) if luogo_el else "Genova"
        
        eventi.append({
            "titolo": titolo,
            "data": data_parsata,
            "data_raw": data_raw,
            "luogo": luogo,
            "url": href,
            "fonte": "genovatoday.it",
            "scraped_at": datetime.now().isoformat(),
        })

    print(f"  GenovaToday: {len(eventi)} eventi trovati")
    return eventi
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filtro", choices=["oggi", "domani", "weekend"], default=None)
    parser.add_argument("--data-inizio", type=str, default=None, help="Data inizio YYYY-MM-DD")
    parser.add_argument("--data-fine", type=str, default=None, help="Data fine YYYY-MM-DD")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    eventi = []
    if args.filtro:
        eventi = scrape_genovatoday(filtro=args.filtro)
    elif args.data_inizio and args.data_fine:
        try:
            d_inizio = date.fromisoformat(args.data_inizio)
            d_fine = date.fromisoformat(args.data_fine)
            eventi = scrape_genovatoday(data_inizio=d_inizio, data_fine=d_fine)
        except ValueError:
            print("Formato data non valido. Usa YYYY-MM-DD")
    
    eventi.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    risultato = {
        "generato_il": datetime.now().isoformat(),
        "filtro": args.filtro,
        "totale": len(eventi),
        "eventi": eventi
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(risultato, f, ensure_ascii=False, indent=2)
        print(f"\nSalvato in {args.output} ({len(eventi)} eventi)")
    else:
        print(json.dumps(risultato, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
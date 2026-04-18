"""
Aggregatore eventi Genova
Scraper per: mentelocale.it con filtri per data
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


def parse_data_mentelocale(data_str: str) -> tuple:
    """
    Parsa le date di MenteLocale
    Formati:
    - "18/04/2026" -> data singola
    - "Dal 17/04/2026 al 19/04/2026" -> intervallo
    Restituisce (data_inizio, data_fine)
    """
    if not data_str:
        return None, None
    
    # Intervallo: Dal 17/04/2026 al 19/04/2026
    m_intervallo = re.search(r"Dal\s+(\d{2}/\d{2}/\d{4})\s+al\s+(\d{2}/\d{2}/\d{4})", data_str)
    if m_intervallo:
        return m_intervallo.group(1), m_intervallo.group(2)
    
    # Data singola: 18/04/2026
    m_singola = re.match(r"(\d{2}/\d{2}/\d{4})", data_str)
    if m_singola:
        return m_singola.group(1), None
    
    return None, None


def converti_data_italiana(data_str: str) -> str | None:
    """Converte DD/MM/YYYY in YYYY-MM-DD"""
    if not data_str:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", data_str)
    if m:
        g, mese, anno = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(anno, mese, g).isoformat()
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


def scrape_mentelocale(filtro: str = None, data_target: date = None) -> list[dict]:
    """
    MenteLocale con filtro date via URL
    Filtri disponibili:
    - "oggi": eventi di oggi
    - "domani": eventi di domani
    - "weekend": eventi del weekend
    """
    eventi = []
    
    if filtro == "oggi":
        url = "https://www.mentelocale.it/genova/eventi/oggi/"
    elif filtro == "domani":
        url = "https://www.mentelocale.it/genova/eventi/domani/"
    elif filtro == "weekend":
        url = "https://www.mentelocale.it/genova/eventi/weekend/"
    elif data_target:
        data_str = data_target.strftime("%d-%m-%Y")
        url = f"https://www.mentelocale.it/genova/eventi/data/{data_str}/"
    else:
        return eventi
    
    print(f"  -> MenteLocale: {url}")
    soup = get(url)
    if not soup:
        return eventi
    
    # Trova il container degli eventi
    container = soup.find("div", class_="ElencoEventi")
    if not container:
        print("  [DEBUG] Container .ElencoEventi non trovato")
        return eventi
    
    eventi_div = container.find_all("div", class_="Evento")
    print(f"  [DEBUG] Trovati {len(eventi_div)} eventi")
    
    for ev in eventi_div:
        # Link e titolo
        link_el = ev.find("a")
        if not link_el:
            continue
        
        href = link_el.get("href")
        if href and not href.startswith("http"):
            href = "https://www.mentelocale.it" + href
        
        # Titolo
        titolo_el = link_el.find("span", class_="Titolo")
        titolo = titolo_el.get_text(strip=True) if titolo_el else ""
        
        # Immagine
        img_el = link_el.find("img")
        img_url = ""
        if img_el:
            img_url = img_el.get("data-src") or img_el.get("src", "")
            if img_url and not img_url.startswith("http"):
                img_url = "https://www.mentelocale.it" + img_url
        
        # Data
        data_el = link_el.find("span", class_="Date")
        data_raw = data_el.get_text(strip=True) if data_el else ""
        data_inizio_raw, data_fine_raw = parse_data_mentelocale(data_raw)
        
        data_inizio = converti_data_italiana(data_inizio_raw) if data_inizio_raw else None
        data_fine = converti_data_italiana(data_fine_raw) if data_fine_raw else None
        
        # Luogo (dai tags)
        luogo = "Genova"
        tags_ul = ev.find("ul", class_="Tags")
        if tags_ul:
            provincia_li = tags_ul.find("li")
            if provincia_li:
                luogo_link = provincia_li.find("a", class_="Provincia")
                if luogo_link:
                    luogo = luogo_link.get_text(strip=True)
        
        eventi.append({
            "titolo": titolo,
            "data": data_inizio,
            "data_inizio": data_inizio,
            "data_fine": data_fine,
            "data_raw": data_raw,
            "luogo": luogo,
            "url": href,
            "immagine": img_url,
            "fonte": "mentelocale.it",
            "scraped_at": datetime.now().isoformat(),
        })
    
    print(f"  MenteLocale: {len(eventi)} eventi trovati")
    return eventi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filtro", choices=["oggi", "domani", "weekend"], required=True)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    eventi = scrape_mentelocale(filtro=args.filtro)
    
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
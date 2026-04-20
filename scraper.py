"""
Aggregatore eventi Genova - MenteLocale
"""

import requests
import json
import argparse
import re
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  [ERRORE] {url} -> {e}")
        return None


def scrape_mentelocale(filtro: str = None) -> list[dict]:
    """Scraping eventi da MenteLocale"""
    eventi = []
    
    if filtro == "oggi":
        url = "https://www.mentelocale.it/genova/eventi/oggi/"
    elif filtro == "domani":
        url = "https://www.mentelocale.it/genova/eventi/domani/"
    elif filtro == "weekend":
        url = "https://www.mentelocale.it/genova/eventi/weekend/"
    else:
        return eventi
    
    print(f"  -> MenteLocale: {url}")
    soup = get(url)
    if not soup:
        return eventi
    
    container = soup.find("div", class_="ElencoEventi")
    if not container:
        return eventi
    
    for ev in container.find_all("div", class_="Evento"):
        link_el = ev.find("a")
        if not link_el:
            continue
        
        href = link_el.get("href")
        if href and not href.startswith("http"):
            href = "https://www.mentelocale.it" + href
        
        titolo_el = link_el.find("span", class_="Titolo")
        titolo = titolo_el.get_text(strip=True) if titolo_el else ""
        
        data_el = link_el.find("span", class_="Date")
        data_raw = data_el.get_text(strip=True) if data_el else ""
        
        # Estrai luogo
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
            "data_raw": data_raw,
            "luogo": luogo,
            "url": href,
            "fonte": "mentelocale.it",
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
    else:
        print(json.dumps(risultato, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
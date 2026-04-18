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
    
    # ISO completo con timezone: 2025-04-18T10:00:00+02:00
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]\d{2}:\d{2}.*)?", testo)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    
    # DD/MM/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            pass
    
    return None


def get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  [ERRORE] {url} -> {e}")
        return None


def scrape_genovatoday(filtro: str = None, data_inizio: str = None, data_fine: str = None) -> list[dict]:
    """
    GenovaToday con filtro date via URL
    Filtri disponibili:
    - "oggi": eventi di oggi
    - "domani": eventi di domani  
    - "weekend": eventi del weekend (sabato e domenica)
    Oppure usa data_inizio e data_fine in formato YYYY-MM-DD
    """
    eventi = []
    
    # Costruisci l'URL con il filtro appropriato
    if filtro:
        oggi = date.today()
        if filtro == "oggi":
            url = f"https://www.genovatoday.it/eventi/dal/{oggi.isoformat()}/al/{oggi.isoformat()}/"
        elif filtro == "domani":
            domani = oggi + timedelta(days=1)
            url = f"https://www.genovatoday.it/eventi/dal/{domani.isoformat()}/al/{domani.isoformat()}/"
        elif filtro == "weekend":
            giorni_a_sab = (5 - oggi.weekday()) % 7
            if giorni_a_sab == 0:
                giorni_a_sab = 7
            sabato = oggi + timedelta(days=giorni_a_sab)
            domenica = sabato + timedelta(days=1)
            url = f"https://www.genovatoday.it/eventi/dal/{sabato.isoformat()}/al/{domenica.isoformat()}/"
        else:
            url = "https://www.genovatoday.it/eventi/"
    elif data_inizio and data_fine:
        url = f"https://www.genovatoday.it/eventi/dal/{data_inizio}/al/{data_fine}/"
    else:
        url = "https://www.genovatoday.it/eventi/"
    
    print(f"  -> GenovaToday: {url}")
    soup = get(url)
    if not soup:
        return eventi

    # Cerca solo gli articoli che sono eventi (di solito hanno una classe specifica)
    # Escludiamo l'header che contiene link promozionali
    articles = soup.find_all("article")
    
    # Filtra gli articoli: escludi quelli che sono chiaramente notizie/articoli
    for article in articles:
        # Cerca il link all'articolo
        link_el = article.find("a", href=True)
        titolo_el = article.find(["h2", "h3"])
        
        if not link_el or not titolo_el:
            continue
        
        titolo = titolo_el.get_text(strip=True)
        if not titolo or len(titolo) < 5:
            continue
        
        # Salta articoli che sembrano notizie (contengono parole chiave)
        parole_notizie = ["notizia", "cronaca", "politica", "sport", "economia", "video", "foto"]
        if any(parola in titolo.lower() for parola in parole_notizie):
            continue
        
        href = link_el["href"]
        if not href.startswith("http"):
            href = "https://www.genovatoday.it" + href
        
        # Cerca la data nell'articolo
        time_el = article.find("time")
        data_raw = ""
        data_parsata = None
        if time_el:
            data_raw = time_el.get("datetime", "") or time_el.get_text(strip=True)
            data_parsata = parse_data_it(data_raw) if data_raw else None
        
        # Cerca il luogo
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
    parser.add_argument("--filtro", choices=["oggi", "domani", "weekend"], default=None,
                        help="Filtro per data: oggi, domani, weekend")
    parser.add_argument("--output", type=str, default=None,
                        help="File di output JSON")
    args = parser.parse_args()

    if args.filtro:
        eventi = scrape_genovatoday(filtro=args.filtro)
    else:
        eventi = scrape_genovatoday()
    
    eventi.sort(key=lambda e: e.get("data") or "9999-99-99")
    
    risultato = {
        "generato_il": datetime.now().isoformat(),
        "filtro": args.filtro or "tutti",
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
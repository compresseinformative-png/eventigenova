"""
Aggregatore eventi Genova
Scraper per: genovatoday.it e mentelocale.it con filtri per data
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

MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def parse_data_it(testo: str) -> str | None:
    """Parsa date in vari formati, restituisce YYYY-MM-DD"""
    if not testo:
        return None
    
    testo = testo.strip()
    
    # ISO con timezone
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
    
    # DD-MM-YYYY
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            pass
    
    # DD mese YYYY
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", testo)
    if m:
        g, mese_str, anno = int(m.group(1)), m.group(2)[:3], int(m.group(3))
        for nome, num in MESI_IT.items():
            if nome.startswith(mese_str):
                try:
                    return date(anno, num, g).isoformat()
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
    """GenovaToday con filtro date via URL"""
    eventi = []
    
    # Costruisci URL con filtro
    if filtro:
        oggi = date.today()
        if filtro == "oggi":
            url = f"https://www.genovatoday.it/eventi/dal/{oggi.isoformat()}/al/{oggi.isoformat()}/"
        elif filtro == "domani":
            domani = oggi + timedelta(days=1)
            url = f"https://www.genovatoday.it/eventi/dal/{domani.isoformat()}/al/{domani.isoformat()}/"
        elif filtro == "weekend":
            giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
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

    articles = soup.find_all("article")

    for article in articles:
        link_el = article.find("a", href=True)
        titolo_el = article.find(["h2", "h3"])
        if not link_el or not titolo_el:
            continue

        titolo = titolo_el.get_text(strip=True)
        if not titolo:
            continue

        href = link_el["href"]
        if not href.startswith("http"):
            href = "https://www.genovatoday.it" + href

        time_el = article.find("time")
        data_raw = time_el.get("datetime", "") or time_el.get_text(strip=True) if time_el else ""
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


def scrape_mentelocale(target_date: date = None) -> list[dict]:
    """
    MenteLocale: eventi per una data specifica
    Usa URL: /genova/eventi/data/DD-MM-AAAA/
    """
    eventi = []
    
    if not target_date:
        target_date = date.today()
    
    # Formato data GG-MM-AAAA per MenteLocale
    data_str = target_date.strftime("%d-%m-%Y")
    url = f"https://www.mentelocale.it/genova/eventi/data/{data_str}/"
    
    print(f"  -> MenteLocale: {url}")
    soup = get(url)
    if not soup:
        return eventi

    # Cerca gli eventi nella pagina (di solito sono in article o div con classi specifiche)
    # Prova diversi selettori comuni
    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"event|card|item", re.I))
    
    for article in articles:
        # Cerca il titolo e il link
        link_el = article.find("a", href=True)
        titolo_el = article.find(["h2", "h3", "h4"])
        
        if not link_el or not titolo_el:
            continue
        
        titolo = titolo_el.get_text(strip=True)
        if not titolo or len(titolo) < 5:
            continue
        
        href = link_el["href"]
        if not href.startswith("http"):
            href = "https://www.mentelocale.it" + href
        
        # Cerca la descrizione/luogo
        testo = article.get_text(" ", strip=True)
        
        # Cerca luogo (spesso dopo "dove:" o simili)
        luogo_match = re.search(r"(?:dove|location|presso)[:\s]+([^,.]+)", testo, re.I)
        luogo = luogo_match.group(1).strip() if luogo_match else "Genova"
        
        eventi.append({
            "titolo": titolo,
            "data": target_date.isoformat(),
            "data_raw": data_str,
            "luogo": luogo,
            "url": href,
            "fonte": "mentelocale.it",
            "scraped_at": datetime.now().isoformat(),
        })

    print(f"  MenteLocale: {len(eventi)} eventi trovati per il {data_str}")
    return eventi


def deduplica(eventi: list[dict]) -> list[dict]:
    """Rimuove duplicati basati su titolo e data"""
    visti = set()
    unici = []
    for e in eventi:
        chiave = (re.sub(r"\s+", " ", e["titolo"].lower().strip())[:60], e.get("data") or "")
        if chiave not in visti:
            visti.add(chiave)
            unici.append(e)
    return unici


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fonte", choices=["genovatoday", "mentelocale", "tutte"], default="tutte")
    parser.add_argument("--filtro", choices=["oggi", "domani", "weekend"], default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    tutti = []
    
    if args.fonte in ("genovatoday", "tutte"):
        print("\n[GenovaToday]")
        if args.filtro:
            tutti.extend(scrape_genovatoday(filtro=args.filtro))
        else:
            tutti.extend(scrape_genovatoday())
    
    if args.fonte in ("mentelocale", "tutte"):
        print("\n[MenteLocale]")
        if args.filtro == "oggi":
            tutti.extend(scrape_mentelocale(date.today()))
        elif args.filtro == "domani":
            tutti.extend(scrape_mentelocale(date.today() + timedelta(days=1)))
        elif args.filtro == "weekend":
            giorni_a_sab = (5 - date.today().weekday()) % 7 or 7
            sabato = date.today() + timedelta(days=giorni_a_sab)
            domenica = sabato + timedelta(days=1)
            tutti.extend(scrape_mentelocale(sabato))
            tutti.extend(scrape_mentelocale(domenica))
        else:
            # Se nessun filtro, prendi oggi
            tutti.extend(scrape_mentelocale(date.today()))

    tutti = deduplica(tutti)
    tutti.sort(key=lambda e: e.get("data") or "9999-99-99")

    risultato = {"generato_il": datetime.now().isoformat(), "totale": len(tutti), "eventi": tutti}

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(risultato, f, ensure_ascii=False, indent=2)
        print(f"\nSalvato in {args.output} ({len(tutti)} eventi)")
    else:
        print(json.dumps(risultato, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
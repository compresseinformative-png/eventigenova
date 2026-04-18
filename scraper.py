"""
Aggregatore eventi Genova
Scraper per: genovatoday.it/eventi/ e mentelocale.it/genova/eventi/

Dipendenze:
    pip install requests beautifulsoup4 lxml

Uso:
    python scraper.py                  # stampa JSON su stdout
    python scraper.py --output eventi.json
    python scraper.py --fonte genovatoday
    python scraper.py --fonte mentelocale
"""

import requests
import json
import argparse
import re
from datetime import datetime, date
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# --------------------------------------------------------------------------- #
# Utilità
# --------------------------------------------------------------------------- #

MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

def parse_data_it(testo: str) -> str | None:
    """
    Prova a convertire una stringa di data italiana in formato ISO (YYYY-MM-DD).
    Gestisce formati come:
      - "18 aprile 2026"
      - "18/04/2026"
      - "2026-04-18"
      - "Sab 18 Apr"
    """
    testo = testo.strip().lower()

    # già ISO
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", testo)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # DD/MM/YYYY o DD/MM/YY
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        return date(y, mes, g).isoformat()

    # "18 aprile 2026" o "18 apr 2026"
    m = re.search(r"(\d{1,2})\s+([a-zà-ü]+)\s+(\d{4})", testo)
    if m:
        g = int(m.group(1))
        mese_str = m.group(2)[:3]  # abbreviazione
        anno = int(m.group(3))
        for nome, num in MESI_IT.items():
            if nome.startswith(mese_str):
                try:
                    return date(anno, num, g).isoformat()
                except ValueError:
                    pass

    # "18 aprile" senza anno → assume anno corrente
    m = re.search(r"(\d{1,2})\s+([a-zà-ü]+)", testo)
    if m:
        g = int(m.group(1))
        mese_str = m.group(2)[:3]
        anno = datetime.now().year
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
        print(f"  [ERRORE] {url} → {e}")
        return None


# --------------------------------------------------------------------------- #
# Scraper GenovaToday
# --------------------------------------------------------------------------- #

def scrape_genovatoday(max_pagine: int = 3) -> list[dict]:
    """
    Scarica gli eventi da genovatoday.it/eventi/
    La sezione usa il motore Citynews: ogni card evento ha
    classe .article-list-item con titolo, data e link.
    """
    eventi = []
    base = "https://www.genovatoday.it/eventi/"

    for pagina in range(1, max_pagine + 1):
        url = base if pagina == 1 else f"{base}?page={pagina}"
        print(f"  → GenovaToday p.{pagina}: {url}")
        soup = get(url)
        if not soup:
            break

        # Le card articolo/evento su Citynews
        cards = soup.select("article.article-list-item, div.event-card, li.event-item")

        # fallback: cerca qualsiasi blocco con link a /eventi/
        if not cards:
            cards = [
                a.find_parent("article") or a.find_parent("li") or a.find_parent("div")
                for a in soup.select("a[href*='/eventi/']")
                if a.find_parent("article") or a.find_parent("li")
            ]
            cards = [c for c in cards if c]

        if not cards:
            print("    nessuna card trovata — struttura HTML cambiata?")
            break

        for card in cards:
            titolo_el = card.select_one("h2, h3, .title, .article-title")
            data_el = card.select_one("time, .date, .event-date, [class*='date']")
            link_el = card.select_one("a[href]")
            luogo_el = card.select_one(".location, .place, [class*='place'], [class*='location']")

            titolo = titolo_el.get_text(strip=True) if titolo_el else None
            if not titolo:
                continue

            data_raw = ""
            if data_el:
                data_raw = data_el.get("datetime", "") or data_el.get_text(strip=True)

            eventi.append({
                "titolo": titolo,
                "data": parse_data_it(data_raw) if data_raw else None,
                "data_raw": data_raw,
                "luogo": luogo_el.get_text(strip=True) if luogo_el else "Genova",
                "url": link_el["href"] if link_el else url,
                "fonte": "genovatoday.it",
                "scraped_at": datetime.now().isoformat(),
            })

        # stop se non ci sono link "pagina successiva"
        if not soup.select("a[rel='next'], .pagination .next, a:contains('Successiva')"):
            break

    print(f"  GenovaToday: {len(eventi)} eventi trovati")
    return eventi


# --------------------------------------------------------------------------- #
# Scraper MenteLocale
# --------------------------------------------------------------------------- #

def scrape_mentelocale(max_pagine: int = 3) -> list[dict]:
    """
    Scarica gli eventi da mentelocale.it/genova/eventi/
    MenteLocale usa un layout a lista con elementi .evento o simili.
    Supporta anche URL per data: /oggi/ /domani/ /weekend/
    """
    eventi = []
    base = "https://www.mentelocale.it/genova/eventi/"

    for pagina in range(1, max_pagine + 1):
        url = base if pagina == 1 else f"{base}?pagina={pagina}"
        print(f"  → MenteLocale p.{pagina}: {url}")
        soup = get(url)
        if not soup:
            break

        # MenteLocale usa tipicamente .evento, .event-item, article
        cards = soup.select(".evento, .event-item, article.event, li.evento")

        if not cards:
            # fallback generico
            cards = soup.select("article, li")
            cards = [c for c in cards if c.select_one("a[href*='/eventi/']")]

        if not cards:
            print("    nessuna card trovata — struttura HTML cambiata?")
            break

        for card in cards:
            titolo_el = card.select_one("h2, h3, .titolo, .title, strong")
            data_el = card.select_one("time, .data, .date, [class*='data'], [class*='date']")
            link_el = card.select_one("a[href]")
            luogo_el = card.select_one(".luogo, .location, .posto, [class*='luogo']")
            desc_el = card.select_one("p, .descrizione, .description")

            titolo = titolo_el.get_text(strip=True) if titolo_el else None
            if not titolo:
                continue

            data_raw = ""
            if data_el:
                data_raw = data_el.get("datetime", "") or data_el.get_text(strip=True)

            eventi.append({
                "titolo": titolo,
                "data": parse_data_it(data_raw) if data_raw else None,
                "data_raw": data_raw,
                "luogo": luogo_el.get_text(strip=True) if luogo_el else "Genova",
                "descrizione": desc_el.get_text(strip=True)[:200] if desc_el else None,
                "url": link_el["href"] if link_el else url,
                "fonte": "mentelocale.it",
                "scraped_at": datetime.now().isoformat(),
            })

        # stop se non c'è paginazione
        if not soup.select("a[rel='next'], .paginazione .next, a.prossima"):
            break

    print(f"  MenteLocale: {len(eventi)} eventi trovati")
    return eventi


# --------------------------------------------------------------------------- #
# Deduplicazione
# --------------------------------------------------------------------------- #

def deduplica(eventi: list[dict]) -> list[dict]:
    """
    Rimuove duplicati basandosi su titolo normalizzato + data.
    Tiene il primo incontrato (priorità alla fonte con più dati).
    """
    visti = set()
    unici = []
    for e in eventi:
        chiave = (
            re.sub(r"\s+", " ", e["titolo"].lower().strip()),
            e.get("data") or "",
        )
        if chiave not in visti:
            visti.add(chiave)
            unici.append(e)
    return unici


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Scraper eventi Genova")
    parser.add_argument("--fonte", choices=["genovatoday", "mentelocale", "tutte"],
                        default="tutte", help="Quale sorgente usare")
    parser.add_argument("--pagine", type=int, default=3,
                        help="Numero massimo di pagine per sorgente")
    parser.add_argument("--output", type=str, default=None,
                        help="Salva JSON su file invece di stamparlo")
    args = parser.parse_args()

    tutti = []

    if args.fonte in ("genovatoday", "tutte"):
        print("\n[GenovaToday]")
        tutti.extend(scrape_genovatoday(args.pagine))

    if args.fonte in ("mentelocale", "tutte"):
        print("\n[MenteLocale]")
        tutti.extend(scrape_mentelocale(args.pagine))

    tutti = deduplica(tutti)

    # ordina per data (None in fondo)
    tutti.sort(key=lambda e: e.get("data") or "9999-99-99")

    risultato = {
        "generato_il": datetime.now().isoformat(),
        "totale": len(tutti),
        "eventi": tutti,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(risultato, f, ensure_ascii=False, indent=2)
        print(f"\nSalvato in {args.output} ({len(tutti)} eventi)")
    else:
        print(json.dumps(risultato, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""
Aggregatore eventi Genova
Scraper per: genovatoday.it/eventi/ e mentelocale.it/genova/
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

MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def parse_data_it(testo: str) -> str | None:
    testo = testo.strip().lower()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", testo)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", testo)
    if m:
        g, mese_str, anno = int(m.group(1)), m.group(2)[:3], int(m.group(3))
        for nome, num in MESI_IT.items():
            if nome.startswith(mese_str):
                try:
                    return date(anno, num, g).isoformat()
                except ValueError:
                    pass
    m = re.search(r"(\d{1,2})\s+([a-z]+)", testo)
    if m:
        g, mese_str = int(m.group(1)), m.group(2)[:3]
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
        print(f"  [ERRORE] {url} -> {e}")
        return None


def scrape_mentelocale() -> list[dict]:
    """
    MenteLocale mostra gli eventi sulla homepage /genova/ come link
    con date nel formato 'Dal DD/MM/YYYY al DD/MM/YYYY'
    """
    eventi = []
    url = "https://www.mentelocale.it/genova/"
    print(f"  -> MenteLocale: {url}")
    soup = get(url)
    if not soup:
        return eventi

    data_pattern = re.compile(r"[Dd]al\s+(\d{1,2}/\d{1,2}/\d{4})")

    # Ogni evento e' un link a /genova/NUMERO-titolo.htm
    seen_urls = set()
    for a in soup.find_all("a", href=re.compile(r"/genova/\d+-.+\.htm")):
        href = a["href"]
        if not href.startswith("http"):
            href = "https://www.mentelocale.it" + href
        if href in seen_urls:
            continue
        seen_urls.add(href)

        titolo = a.get_text(strip=True)
        if not titolo or len(titolo) < 5:
            continue

        # cerca data nel testo del contenitore padre
        testo = ""
        parent = a.parent
        for _ in range(5):
            if parent:
                testo = parent.get_text(" ", strip=True)
                if data_pattern.search(testo):
                    break
                parent = parent.parent

        m = data_pattern.search(testo)
        data_iso = parse_data_it(m.group(1)) if m else None

        eventi.append({
            "titolo": titolo,
            "data": data_iso,
            "data_raw": m.group(0) if m else "",
            "luogo": "Genova",
            "url": href,
            "fonte": "mentelocale.it",
            "scraped_at": datetime.now().isoformat(),
        })

    print(f"  MenteLocale: {len(eventi)} eventi trovati")
    return eventi


def scrape_genovatoday(max_pagine: int = 3) -> list[dict]:
    """
    GenovaToday usa Citynews: articoli <article> con h2/h3 + <time datetime="...">
    """
    eventi = []
    base = "https://www.genovatoday.it/eventi/"

    for pagina in range(1, max_pagine + 1):
        url = base if pagina == 1 else f"{base}?page={pagina}"
        print(f"  -> GenovaToday p.{pagina}: {url}")
        soup = get(url)
        if not soup:
            break

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
            data_raw = ""
            if time_el:
                data_raw = time_el.get("datetime", "") or time_el.get_text(strip=True)

            luogo_el = article.find(class_=re.compile(r"location|place|luogo", re.I))
            luogo = luogo_el.get_text(strip=True) if luogo_el else "Genova"

            eventi.append({
                "titolo": titolo,
                "data": parse_data_it(data_raw) if data_raw else None,
                "data_raw": data_raw,
                "luogo": luogo,
                "url": href,
                "fonte": "genovatoday.it",
                "scraped_at": datetime.now().isoformat(),
            })

        if not soup.find("a", rel="next"):
            break

    print(f"  GenovaToday: {len(eventi)} eventi trovati")
    return eventi


def deduplica(eventi: list[dict]) -> list[dict]:
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
    parser.add_argument("--pagine", type=int, default=3)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    tutti = []
    if args.fonte in ("genovatoday", "tutte"):
        print("\n[GenovaToday]")
        tutti.extend(scrape_genovatoday(args.pagine))
    if args.fonte in ("mentelocale", "tutte"):
        print("\n[MenteLocale]")
        tutti.extend(scrape_mentelocale())

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

"""
Aggregatore eventi Genova
Scraper per: genovatoday.it/eventi/ e mentelocale.it/genova/
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
    """
    Parsa date in vari formati italiani e ISO, restituisce YYYY-MM-DD
    """
    if not testo:
        return None
    
    testo = testo.strip()
    
    # 1) ISO completo con timezone: 2025-04-18T10:00:00+02:00
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]\d{2}:\d{2}.*)?", testo)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    
    # 2) DD/MM/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            pass
    
    # 3) DD-MM-YYYY
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", testo)
    if m:
        g, mes, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mes, g).isoformat()
        except ValueError:
            pass
    
    # 4) DD mese YYYY
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
    """
    GenovaToday con filtro date via URL
    Filtri disponibili:
    - "oggi": eventi di oggi
    - "domani": eventi di domani  
    - "weekend": eventi del weekend
    - "settimana": eventi di questa settimana
    - "prossima_settimana": eventi della prossima settimana
    - "mese": eventi di questo mese
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
            giorni_a_sab = (5 - oggi.weekday()) % 7 or 7
            sabato = oggi + timedelta(days=giorni_a_sab)
            domenica = sabato + timedelta(days=1)
            url = f"https://www.genovatoday.it/eventi/dal/{sabato.isoformat()}/al/{domenica.isoformat()}/"
        elif filtro == "settimana":
            lunedi = oggi - timedelta(days=oggi.weekday())
            domenica = lunedi + timedelta(days=6)
            url = f"https://www.genovatoday.it/eventi/dal/{lunedi.isoformat()}/al/{domenica.isoformat()}/"
        elif filtro == "prossima_settimana":
            lunedi_prossimo = oggi + timedelta(days=(7 - oggi.weekday()))
            domenica_prossima = lunedi_prossimo + timedelta(days=6)
            url = f"https://www.genovatoday.it/eventi/dal/{lunedi_prossimo.isoformat()}/al/{domenica_prossima.isoformat()}/"
        elif filtro == "mese":
            primo_del_mese = oggi.replace(day=1)
            if oggi.month == 12:
                ultimo_del_mese = oggi.replace(year=oggi.year+1, month=1, day=1) - timedelta(days=1)
            else:
                ultimo_del_mese = oggi.replace(month=oggi.month+1, day=1) - timedelta(days=1)
            url = f"https://www.genovatoday.it/eventi/dal/{primo_del_mese.isoformat()}/al/{ultimo_del_mese.isoformat()}/"
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

    # Estrai gli eventi dalla pagina filtrata
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

        # La data è già implicita nel filtro, ma la prendiamo dal testo se disponibile
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

    pattern_intervallo = re.compile(r"[Dd]al\s+(\d{1,2}/\d{1,2}/\d{4})\s+[Aa]l\s+(\d{1,2}/\d{1,2}/\d{4})")
    pattern_singolo = re.compile(r"[Dd]al\s+(\d{1,2}/\d{1,2}/\d{4})")

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

        testo = ""
        parent = a.parent
        for _ in range(5):
            if parent:
                testo = parent.get_text(" ", strip=True)
                parent = parent.parent

        m_intervallo = pattern_intervallo.search(testo)
        if m_intervallo:
            data_inizio_str = m_intervallo.group(1)
            data_fine_str = m_intervallo.group(2)
            data_inizio = parse_data_it(data_inizio_str)
            data_fine = parse_data_it(data_fine_str)
            data_raw = f"Dal {data_inizio_str} al {data_fine_str}"
        else:
            m_singolo = pattern_singolo.search(testo)
            if m_singolo:
                data_inizio_str = m_singolo.group(1)
                data_inizio = parse_data_it(data_inizio_str)
                data_fine = None
                data_raw = f"Dal {data_inizio_str}"
            else:
                data_inizio = None
                data_fine = None
                data_raw = ""

        eventi.append({
            "titolo": titolo,
            "data": data_inizio,
            "data_inizio": data_inizio,
            "data_fine": data_fine,
            "data_raw": data_raw,
            "luogo": "Genova",
            "url": href,
            "fonte": "mentelocale.it",
            "scraped_at": datetime.now().isoformat(),
        })

    print(f"  MenteLocale: {len(eventi)} eventi trovati")
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
    parser.add_argument("--filtro", choices=["oggi", "domani", "weekend", "settimana", "prossima_settimana", "mese"], default=None)
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
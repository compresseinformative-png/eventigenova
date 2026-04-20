import requests
import json
import argparse
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"ERRORE: {e}")
        return None

def scrape_mentelocale(filtro):
    eventi = []
    
    if filtro == "oggi":
        url = "https://www.mentelocale.it/genova/eventi/oggi/"
    elif filtro == "domani":
        url = "https://www.mentelocale.it/genova/eventi/domani/"
    elif filtro == "weekend":
        url = "https://www.mentelocale.it/genova/eventi/weekend/"
    else:
        return eventi
    
    print(f"URL: {url}")
    soup = get(url)
    if not soup:
        return eventi
    
    container = soup.find("div", class_="ElencoEventi")
    if not container:
        print("Container non trovato")
        return eventi
    
    for ev in container.find_all("div", class_="Evento"):
        link = ev.find("a")
        if not link:
            continue
        
        href = link.get("href")
        if href and not href.startswith("http"):
            href = "https://www.mentelocale.it" + href
        
        titolo_span = link.find("span", class_="Titolo")
        titolo = titolo_span.get_text(strip=True) if titolo_span else ""
        
        data_span = link.find("span", class_="Date")
        data_raw = data_span.get_text(strip=True) if data_span else ""
        
        eventi.append({
            "titolo": titolo,
            "data": data_raw,
            "url": href,
            "fonte": "mentelocale.it"
        })
    
    print(f"Trovati {len(eventi)} eventi")
    return eventi

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--filtro", required=True)
    args = parser.parse_args()
    
    eventi = scrape_mentelocale(args.filtro)
    print(json.dumps(eventi, ensure_ascii=False, indent=2))
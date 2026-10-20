#!/usr/bin/env python3
"""Overvåk ledige elgjakttilbud i Nordland på Inatur.

Leser søket med en ekte nettleser (Playwright), sammenligner både hvilke
jaktfelt som vises og kortene under «Kjøp/søk jakt her», og sender push via ntfy.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE = "https://www.inatur.no"
FILTERS = [
    {"felt": "arter", "sokeord": "elg"},
    {"felt": "fylker", "sokeord": "Nordland"},
    {"felt": "type", "sokeord": "storvilttilbud"},
]
SEARCH_URL = (
    BASE + "/sok/storvilttilbud?" +
    urlencode({"f": json.dumps(FILTERS, separators=(",", ":"), ensure_ascii=False),
               "ledig": "true", "p": "0"})
)
STATE_PATH = Path(os.environ.get("STATE_PATH", "state.json"))
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "15"))
PAGE_TIMEOUT_MS = 35000
DETAIL_TIMEOUT_MS = 20000
ID_PATTERN = re.compile(r"/storviltjakt/([0-9a-f]{24})(?:[/?#]|$)", re.I)
EMPTY_PATTERN = re.compile(
    r"(?:ingen\s+(?:treff|resultater|tilbud)|fant\s+ingen|0\s+(?:treff|resultater))", re.I
)
OFFER_START = re.compile(r"^Kjøp/søk\s+(?:jakt|kort)\s+her\s*$", re.I)
OFFER_END = re.compile(
    r"^(?:Om selger|Priser|Jaktregler|Mer detaljert beskrivelse|Om tilbudet|Kontakt selger|Jaktkvoter)$", re.I
)
COMMON_OFFER_LINES = re.compile(
    r"^(?:utløpt|utsolgt|ikke tilgjengelig|kjøp|søknad|søk|velg|"
    r"pris fra\s*\d+.*|tilleggskort|(?:\d{1,2}[./-]\d{1,2}.*))$", re.I
)


def search_page_url(page_number: int) -> str:
    parts = urlsplit(SEARCH_URL)
    params = dict(parse_qsl(parts.query))
    params["p"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def clean(value: str, length: int = 160) -> str:
    return " ".join(str(value or "").split()).strip()[:length]


def get_search_links(page) -> list[dict[str, str]]:
    # Både selve lenketeksten og overskrifter er mulige tittel-kilder.
    anchors = page.locator('a[href*="/storviltjakt/"]').evaluate_all("""anchors =>
      anchors.map(a => ({
        href: a.getAttribute('href') || '',
        title: (a.querySelector('h1,h2,h3,h4,h5')?.textContent ||
                a.getAttribute('aria-label') || a.innerText || '').trim()
      }))
    """)
    products: dict[str, dict[str, str]] = {}
    for anchor in anchors:
        link = urljoin(BASE, anchor["href"])
        match = ID_PATTERN.search(urlsplit(link).path)
        if not match:
            continue
        pid = match.group(1).lower()
        title = clean((anchor["title"] or "").split("\n")[0]) or "Elgjakttilbud"
        if pid not in products or (products[pid]["title"] == "Elgjakttilbud" and title):
            products[pid] = {"id": pid, "url": link, "title": title}
    return list(products.values())


def result_is_empty(body_text: str) -> bool:
    return bool(EMPTY_PATTERN.search(body_text))


def load_search_results(browser) -> list[dict[str, str]]:
    context = browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
    page = context.new_page()
    products: dict[str, dict[str, str]] = {}
    try:
        for number in range(MAX_PAGES):
            url = search_page_url(number)
            print(f"Sjekker søkeresultater side {number + 1}: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            try:
                page.wait_for_function(r"""() => {
                    const text = (document.body?.innerText || '');
                    return document.querySelectorAll('a[href*="/storviltjakt/"]').length > 0
                        || /ingen\s+(treff|resultater|tilbud)|fant\s+ingen|0\s+(treff|resultater)/i.test(text);
                }""", timeout=PAGE_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                page.screenshot(path="inatur-feil-sok.png", full_page=True)
                raise RuntimeError(
                    f"Inatur-søket viste ikke gjenkjennelige tilbud eller en tom-resultat-melding "
                    f"på side {number + 1}. Se inatur-feil-sok.png (lastes opp ved feil)."
                ) from exc
            page.wait_for_timeout(850)  # La asynkrone kort tegnes ferdig
            links = get_search_links(page)
            if not links:
                if result_is_empty(page.locator("body").inner_text(timeout=5000)):
                    return list(products.values())
                raise RuntimeError(f"Ingen gjenkjennelige lenker på søkeside {number+1}")
            new_ids = [item for item in links if item["id"] not in products]
            if not new_ids:
                # Nettstedet kan returnere første side på p>0; stopp da.
                break
            for item in new_ids:
                products[item["id"]] = item
            print(f"  {len(links)} lenker, {len(new_ids)} nye i resultatlisten")
        else:
            raise RuntimeError(
                f"Nådde MAX_PAGES={MAX_PAGES}. Øk grensen for å unngå å miste tilbud."
            )
    finally:
        context.close()
    return list(products.values())


def extract_location(page_text: str) -> str:
    lines = [clean(x) for x in page_text.splitlines() if clean(x)]
    for i, line in enumerate(lines):
        if line.lower() != "beliggenhet":
            continue
        for candidate in lines[i + 1:i + 5]:
            if candidate in ("Powered by Esri", "Kart", "Se kart"):
                continue
            if candidate.lower() in ("viktige datoer", "selger", "kontakt selger"):
                break
            if re.fullmatch(r"[A-Za-zÆØÅæøå .\-/]{3,70}", candidate):
                return candidate
        break
    return ""


def extract_offer_lines(page_text: str) -> list[str]:
    lines = [clean(x, 240) for x in page_text.splitlines() if clean(x, 240)]
    start = next((i for i, s in enumerate(lines) if OFFER_START.match(s)), None)
    if start is None:
        return []
    output = []
    for line in lines[start + 1:]:
        if OFFER_END.match(line):
            break
        output.append(line)
        if len(output) >= 100:
            break
    return output


def offer_changes(old: list[str], new: list[str]) -> list[str]:
    old_set = set(old)
    additions = [line for line in new if line not in old_set]
    significant = [x for x in additions if not COMMON_OFFER_LINES.match(x)]
    return significant[:4]


def enrich_offer(browser, item: dict[str, str], old: dict | None) -> dict:
    """Hent kommune og kort-seksjon. Ved feil behold tidligere data."""
    record = {"title": item["title"], "url": item["url"],
              "location": (old or {}).get("location", ""),
              "offers": (old or {}).get("offers", [])}
    context = browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
    page = context.new_page()
    try:
        page.goto(item["url"], wait_until="domcontentloaded", timeout=DETAIL_TIMEOUT_MS)
        try:
            page.wait_for_function("""() => {
                let t = document.body?.innerText || '';
                return t.includes('Kjøp/søk jakt her') || t.includes('Kjøp/søk kort her')
                    || t.includes('Om selger') || t.includes('Viktige datoer');
            }""", timeout=12000)
        except PlaywrightTimeoutError:
            print(f"Advarsel: Detaljsiden lastet ikke ferdig: {item['url']}")
            return record
        page.wait_for_timeout(650)
        body = page.locator("body").inner_text(timeout=5000)
        record["location"] = extract_location(body) or record["location"]
        # Tom kortseksjon er en gyldig verdi hvis nettstedet selv viser overskriften.
        if OFFER_START.search(body) or re.search(r"Kjøp/søk\s+(?:jakt|kort)\s+her", body, re.I):
            record["offers"] = extract_offer_lines(body)
    except Exception as exc:
        print(f"Advarsel: Kunne ikke kontrollere detaljene for {item['url']}: {exc}")
    finally:
        context.close()
    return record


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != 1 or not isinstance(data.get("products"), dict):
        raise ValueError("state.json har feil format. Ikke slett den uten å forstå følgene.")
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    temp.replace(path)


def build_notifications(old: dict | None, new: dict) -> list[dict[str, str]]:
    if old is None:
        return []  # Første kjøring lærer hvilke jaktfelt og kort som allerede er ute.
    messages = []
    before = old["products"]
    for pid, item in new["products"].items():
        title = clean(item["title"])
        area = item.get("location", "")
        prefix = f"{title}\nOmråde: {area or 'Se lenken for sted'}"
        if pid not in before:
            messages.append({"title": "Nytt elgjakttilbud i Nordland",
                             "message": prefix, "url": item["url"]})
        elif item.get("offers", []) != before[pid].get("offers", []):
            changes = offer_changes(before[pid].get("offers", []), item.get("offers", []))
            details = "\nNytt på siden: " + "; ".join(changes) if changes else "\nJaktkort/salg er endret"
            messages.append({"title": "Endring i jaktkort på Inatur",
                             "message": prefix + details, "url": item["url"]})
    return messages


def send_notification(message: dict[str, str]) -> None:
    if not TOPIC or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", TOPIC):
        raise RuntimeError("Sett GitHub-hemmeligheten NTFY_TOPIC (minst 8 tegn; kun bokstaver, tall, _ og -).")
    # JSON hindrer problemer med norske tegn i HTTP-headere.
    payload = {"topic": TOPIC, "title": message["title"],
               "message": message["message"], "priority": 4,
               "click": message.get("url", SEARCH_URL), "tags": ["deer"]}
    response = requests.post(f"{NTFY_SERVER}/", json=payload, timeout=20)
    response.raise_for_status()
    print("Varsling sendt:", message["title"], message.get("url", ""))


def run() -> None:
    if not TOPIC:
        raise RuntimeError("NTFY_TOPIC mangler. Se oppsett i README.md.")
    previous = load_state(STATE_PATH)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            search_items = load_search_results(browser)
            print(f"Totalt {len(search_items)} aktive jaktfelt/tilbud i søkeresultatet")
            current = {}
            for index, item in enumerate(search_items, start=1):
                print(f"Kontrollerer detaljer {index}/{len(search_items)}: {item['title']}")
                old_record = (previous or {}).get("products", {}).get(item["id"])
                current[item["id"]] = enrich_offer(browser, item, old_record)
        finally:
            browser.close()
    new_state = {"version": 1, "products": current}
    if previous is None:
        print("Første kjøring: lagrer starttilstand uten å varsle om eksisterende tilbud.")
    else:
        alerts = build_notifications(previous, new_state)
        print(f"Fant {len(alerts)} nye/endrede jaktfelttilbud.")
        for msg in alerts:
            send_notification(msg)
    # Skriv først når alle varslene er levert, ellers kan endringer gå tapt.
    if previous != new_state:
        save_state(STATE_PATH, new_state)
        print(f"Lagrer oppdatert status i {STATE_PATH}")
    else:
        print("Ingen endring siden forrige kjøring.")


def main() -> None:
    parser = argparse.ArgumentParser(description="iNatur: varsel om ledige elgjakttilbud i Nordland")
    parser.add_argument("--test-notification", action="store_true",
                        help="Send testvarsel til iPhone, uten å besøke Inatur")
    args = parser.parse_args()
    if args.test_notification:
        send_notification({"title": "Test fra Inatur-varsler",
                           "message": "Varslene fungerer! Nå får du beskjed om nye elgjakttilbud i Nordland.",
                           "url": SEARCH_URL})
    else:
        run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FEIL: {exc}", file=sys.stderr)
        sys.exit(1)

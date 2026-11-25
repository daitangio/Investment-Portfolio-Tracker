#!python
"""Suggest _BOND_ISIN_ALIASES entries from the Treasury's "Scadenze" master data.

DRY-RUN helper: extracts placement("speciale")→market("regolare") ISIN pairs
from the monthly "Scadenze titoli suddivise per anno" PDF published by MEF
(dt.mef.gov.it), sanity-checks each candidate market ISIN against a live
Borsa Italiana MOT scheda page, and prints suggested lines for
MarketDataService._BOND_ISIN_ALIASES. Never writes code or data.

Usage (from the backend container or backend/):
    python scripts/repair_bond_isin_aliases.py [--pdf FILE] [--url URL]

dt.mef.gov.it sits behind Akamai bot protection: if the automatic download is
refused, download the newest edition in a browser and pass --pdf.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

INDEX_URL = "https://www.dt.mef.gov.it/it/debito_pubblico/dati_statistici/scadenze_titoli_suddivise_anno/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
# Official footnote wording: "Il codice ISIN 'speciale' IT… verrà sostituito
# dal codice ISIN 'regolare' IT… al momento dell'eventuale vendita …"
PAIR_RE = re.compile(
    r"speciale.{0,120}?IT[0-9A-Z]{10}.{0,200}?sostituit.{0,200}?IT[0-9A-Z]{10}",
    re.S | re.I,
)
ISIN_RE = re.compile(r"IT[0-9A-Z]{10}")
SCHEDA_RE = re.compile(r"-formatPrice\">\s*<strong>\s*([\d]+(?:[.,][\d]+)?)")


def extract_pairs(pdf_text: str) -> dict[str, str]:
    """placement ISIN -> market ISIN, anchored on the official wording."""
    pairs: dict[str, str] = {}
    for m in PAIR_RE.finditer(pdf_text):
        isins = ISIN_RE.findall(m.group(0))
        if len(isins) >= 2 and isins[0] != isins[-1]:
            pairs[isins[0]] = isins[-1]
    return pairs


def resolve_pdf_url(args: argparse.Namespace) -> str:
    if args.url:
        return args.url
    resp = httpx.get(INDEX_URL, headers=UA, timeout=20.0, follow_redirects=True)
    resp.raise_for_status()
    urls = re.findall(r'href="([^"]*Scadenze[^"]*\.pdf[^"]*)"', resp.text)
    if not urls:
        raise SystemExit("No Scadenze PDF links found on the index page — pass --url or --pdf")
    best = max(urls, key=lambda u: len(u))
    return best if best.startswith("http") else f"https://www.dt.mef.gov.it{best}"


def read_pdf_text(source: str) -> str:
    from pypdf import PdfReader

    if source.startswith("http"):
        print(f"Downloading Scadenze PDF: {source}")
        data = httpx.get(source, headers=UA, timeout=60.0, follow_redirects=True)
        print(f"  HTTP {data.status_code} — {len(data.content)} bytes")
        data.raise_for_status()
        reader = PdfReader(__import__("io").BytesIO(data.content))
    else:
        reader = PdfReader(source)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def verify_scheda(market_isin: str) -> str | None:
    """Live MOT scheda check: HTTP 200, ISIN in page, a price that parses."""
    from services.market_data_service import MarketDataService

    svc = MarketDataService()
    try:
        html = await svc._borsa_italiana_page(market_isin, "btp")
        if html is None or market_isin not in (html or ""):
            return None
        return svc._parse_borsa_last_price(html) or svc._parse_borsa_official_close(html)[0]
    finally:
        await svc._http.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", help="Path to a manually downloaded Scadenze PDF")
    parser.add_argument("--url", help="Direct URL of a Scadenze PDF edition")
    args = parser.parse_args()

    text = read_pdf_text(args.pdf) if args.pdf else read_pdf_text(resolve_pdf_url(args))
    pairs = extract_pairs(text)
    if not pairs:
        lines = [ln.strip() for ln in text.splitlines() if "speciale" in ln.lower()]
        print("No pairs matched the footnote wording. Raw 'speciale' lines for human review:")
        for ln in lines[:20]:
            print(f"  {ln[:300]}")
        return

    print(f"Found {len(pairs)} placement→market pairs:\n")
    for placement, market in sorted(pairs.items()):
        quote = asyncio.run(verify_scheda(market))
        check = f"live MOT scheda quote {quote:.2f}" if quote else "NO scheda page found"
        print(f'    "{placement}": "{market}",  # {check}')

    # Loyalty-premium certificates use a second footnote formula — "(n) ISIN EX
    # IT… (non beneficia del premio fedeltà)" — tied to their row only by
    # footnote number, which pypdf text extraction scrambles. Never auto-pair
    # those: print the raw lines for human review instead.
    ex_lines = sorted({ln.strip()[:220] for ln in text.splitlines() if "ISIN EX" in ln})
    if ex_lines:
        print("\nManual review — 'ISIN EX ... (non beneficia del premio fedeltà)' footnotes")
        print("(premio-fedeltà twins; pair by footnote number against the bond row):")
        for ln in ex_lines:
            print(f"  {ln}")

    print("\nPaste suggested lines (after review) into "
          "MarketDataService._BOND_ISIN_ALIASES — this script never edits code.")


if __name__ == "__main__":
    main()

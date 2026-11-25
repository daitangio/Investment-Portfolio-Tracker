# btpfacile.it fixtures (captured 2026-11-25/26, task 1.1/1.2)

- `btpfacile_IT0005622128.html` — live per-ISIN page for BTP FX 2,7% ott 2027 (HTTP 200, 201919 bytes).
- `btpfacile_LU1900066033_notfound.html` — response body for a non-BTP ISIN (`/it/btp/LU1900066033`):
  the site answers **HTTP 302 → `https://btpfacile.it/it/`** (home page, saved here with `-L`).
  httpx `AsyncClient` does not follow redirects by default, so the 302 is a non-200 → None;
  even if followed, the home page has no price badge → parse returns None.

## Anchors identified on the per-ISIN page (each occurs exactly once)

| Data | Markup | Regex anchor |
|---|---|---|
| Quote (% of nominal) | `<span class="bg-warning fs-1 txt-col-black xtxt-b px-2 py-1">99,58</span>` | `<span class="bg-warning fs-1[^"]*">\s*([\d]+(?:[.,]\d+)?)\s*</span>` |
| Quote (fallback text) | h2/meta: `... con prezzo di 99,58 e la scadenza ...` | `prezzo di\s*([\d]+(?:[.,]\d+)?)` |
| Quote timestamp (structured) | `<span class="fs-6">Ultimo aggiornamento prezzo</span><br /><b>24/11/2026 17:47:24</b>` | `Ultimo aggiornamento prezzo</span><br\s*/?>\s*<b>\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})(?::(\d{2}))?` |
| Quote timestamp (fallback text) | h2/meta: `... ultima quotazione del 24/11/2026 17:47.` | `ultima quotazione del\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})` |

Notes:
- Date format is DD/MM/YYYY HH:MM(:SS), Italian locale, comma decimal separator for the quote.
- Search snippets show some pages render the relative wording `ultima quotazione oggi ore 17:56`
  instead of an absolute date — the parser must handle `oggi ore HH:MM` as "today at HH:MM"
  (covered by task 4.2 tests).
- The quote is % of nominal (same convention as Borsa Italiana MOT) → ÷100 normalization applies.

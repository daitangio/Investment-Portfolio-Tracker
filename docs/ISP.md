
# Come aggiungere le transazioni di Intesa San PAolo

- Fare login sull'home banking, andare sull'archivio
- Selezionare il deposito amministrato.
- Scaricare una o più pdf delle ricevute delle transazioni, chiamate "Conferma operazioni in titoli"
- Aprire l'applicazione investment portfolio banking, Selezionare il secondo menu "Investments": cliccare su Add Portfolio
- Selezionare Intesa San Paolo
- Caricare un pdf alla volta (o un pdf fuso con tutti i dati)


## Funzionalità di importazione patrimonio (SPERIMENTALE)

- Al momento richiede prima una importazione di almeno una transazione (step prcedente)
- Andare su https://www.intesasanpaolo.com/ndce/webapp/asset-invest-v1/patrimonio e scaricare il patrimonio in formato excel

## Placement vs market ISIN (retail BTP dual-ISIN)

From Feb 2025, MEF retail placements (BTP Più, BTP Valore, BTP Italia Sì) carry **two ISINs**:

- **Placement ISIN** ("codice speciale") — used during the collocamento on MOT and kept by the bank in custody; this is what the patrimonio sheet and the app store.
- **Definitive market ISIN** ("codice regolare") — announced by MEF at placement close; the only ISIN quoted on Borsa Italiana MOT (live quotes and official closes).

The app prices custodied placement ISINs through the `MarketDataService._BOND_ISIN_ALIASES` map (`backend/services/market_data_service.py`). Current pairs:

| Placement ISIN (custody) | Market ISIN (quoted) | Bond                         |
| ------------------------ | -------------------- | ---------------------------- |
| IT0005713539             | IT0005713547         | BTP Italia Sì 23GN31 1,60CUM |
| IT0005634792             | IT0005634800         | BTP Più 25FB33 SU PUT        |
| IT0005696320             | IT0005696338         | BTP Valore 10MZ32 SU CUM     |

**Adding a new pair** (when a new retail bond appears in the import without a live quote):

1. Find the definitive ISIN in the MEF placement-close notice ("nuovo codice ISIN"), the Information Memorandum, or the footnote of the monthly *Scadenze titoli suddivise per anno* PDF on dt.mef.gov.it.
2. Run `make repair-bond-isin-aliases` — extracts placement→market pairs from the newest Scadenze PDF and prints suggested `_BOND_ISIN_ALIASES` lines, each verified against a live MOT scheda page (`--pdf <path>` accepts a manually downloaded edition; the site refuses automated fetchers).
3. Paste the suggested line into `_BOND_ISIN_ALIASES` — the script is dry-run only and never edits code.

Lo script di cui sopra funzionaicchia, nel senso che non mi pare trovare tutti gli isin di cui ho bisogno: ho risolton con una chattata su mistral.
Al momento va fattra la manutenzione continua di questo elenco altrimenti il fallback usa l'ultima quotazione caricata dal pdf e sbaglia la valutazione

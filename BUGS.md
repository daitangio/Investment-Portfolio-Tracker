
# Problema con doppi isin per i BTP

The story is now complete: since Feb 2025 (BTP Più first issue), MEF gives retail bonds two ISINs — a placement ISIN that banks keep in custody (what your sheet and the app store), and a definitive market ISIN ("il nuovo codice ISIN" announced at placement close) that actually trades on MOT.

The app prices the custody ISIN, which simply has no quote page anywhere — Euronext included: live.euronext.com serves quotes through an encrypted JS ajax (I got {"ct": "<ciphertext>"}), and two of your three retail ISINs return "Instrument not found" there today anyway.

La soluzione per ora è una mappa statica vedi change [*add-bond-isin-alias-pricing*](openspec/changes/archive/2026-11-23-add-bond-isin-alias-pricing)


# Altro bug add-etf-scheda-na-guard-fix

"When the scheda's Closing Price cell is N.A. mid-session (with a live last trade showing), how should borsa_etf_official_close behave? The last-trade fallback (from the archived add-etfplus-etf-pricing change) currently fires on a None close and would append a mid-session row, violating this change's spec scenario. Which behavior do you want?" → Remove fallback
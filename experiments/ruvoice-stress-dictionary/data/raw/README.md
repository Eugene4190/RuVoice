# Local Wiktionary source data

Put the compressed raw Wiktextract JSONL for the Russian-language Wiktionary edition here:

- raw-wiktextract-data.jsonl.gz

As of the 2026-11-01 source snapshot, the compressed download is about 272.5 MB and expands to about 2.3 GB. The raw stream contains entries in multiple languages; the official tools/wikt_forms.py parser filters lang_code == ru.

Download page:
https://kaikki.org/ruwiktionary/rawdata.html

The pipeline streams the gzip file directly; do not unpack it manually. The dump and intermediate files are excluded from Git.

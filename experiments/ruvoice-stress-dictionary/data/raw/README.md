# Local Wiktionary source data

Put the compressed raw Wiktextract JSONL for the Russian-language Wiktionary edition here:

- raw-wiktextract-data.jsonl.gz

As of the 2026-11-01 source snapshot, the compressed download is about 272.5 MB and expands to about 2.3 GB. The raw stream contains entries in multiple languages; the official tools/wikt_forms.py parser filters lang_code == ru.

Download page:
https://kaikki.org/ruwiktionary/rawdata.html

The pipeline streams the gzip file directly; do not unpack it manually. The dump and intermediate files are excluded from Git.


## Running the separate Russian-edition extractor

The Russian-edition stream is deliberately separate from `project/ruvoice-1.1.3-stage4.9/tools/wikt_forms.py`, which reads Russian entries from the English Wiktionary edition.

After downloading the compressed JSONL file above into this directory, run from the repository root:

```bash
python experiments/ruvoice-stress-dictionary/extract_ruwiktionary_forms.py \
  experiments/ruvoice-stress-dictionary/data/raw/raw-wiktextract-data.jsonl.gz \
  --dump-date 2026-11-01
```

The default outputs are written under `.work/` (ignored by Git):

- `ruwiktionary_forms.tsv` — compact surface forms with marked stress and source descriptors;
- `ruwiktionary_forms_context.jsonl` — one JSON record per source form, retaining morphology, word tags, categories, glosses, etymology, IPA/audio and the original input line number. This separate stream preserves distinct senses even when two articles share the same surface, POS and stress;
- `ruwiktionary_forms_manifest.json` — dump date, input/output/context SHA-256 hashes, article/form/context counts and extractor provenance.

The extractor is intentionally review-only. It does not merge the new edition into AOT/English-Wiktionary, resolve duplicate entries automatically, or write to the production/system/approved dictionaries. Compare exact surface forms, stress alternatives, parts of speech and tags first. Multisyllabic forms without explicit acute or `ё` are withheld rather than guessed.

Current source page for the pinned snapshot: https://kaikki.org/ruwiktionary/rawdata.html (ruwiktionary dump dated 2026-11-01; gzip download listed as 272.5 MB on 2026-11-25).

## Source licensing and attribution

Kaikki's raw Russian-edition data are extracted from Wiktionary and are made available under the same licenses as Wiktionary (CC BY-SA and GFDL). Do not commit the raw dump to this repository. Before redistributing any substantial extracted text, preserve source attribution and verify the applicable share-alike and GFDL requirements. Kaikki asks academic users to cite Tatu Ylonen, “Wiktextract: Wiktionary as Machine-Readable Structured Data,” LREC 2022, pp. 1317–1325, and link to the relevant Kaikki data page.

Sources: https://kaikki.org/ruwiktionary/ ; https://kaikki.org/ruwiktionary/rawdata.html ; https://github.com/tatuylonen/wiktextract

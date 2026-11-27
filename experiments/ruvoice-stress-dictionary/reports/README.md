# Reports and provenance

Reports are kept alongside the generated dictionaries so each export can be traced back to its inputs.

- TSV files list rejected or withheld entries and the reason.
- JSON manifests contain counts and input paths.
- source_versions.json records upstream commit and dataset paths after a full run.

An entry being repeated in a corpus is not proof that its stress is correct.
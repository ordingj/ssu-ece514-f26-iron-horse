# Import provenance

This checkout preserves the destination's initial commit,
`cd711077510cb0be2ca44c6efad5d67fc32bc889`. The original private repository
and its full Git history remain in place.

The source is `ordingj/ece514-project` at commit
`1ef1b5c2c67a4887b1e0dec4c572126bf5c721e6`.
[import-manifest.json](import-manifest.json) records this commit and the source
and destination hashes. It lists the code, fixtures, metadata, and results
that this checkout uses.

## Current package

This checkout contains code for the current protocol. It uses the required
shared functions from the earlier runner in `iron_horse/core.py`. It contains
no earlier experiment entry point or model.

All 13 shared definitions retain the same Python abstract syntax tree.
All 15 current checkpoint definitions outside the command entry point retain
the same tree after the two metadata path changes. Decoder definitions also
retain their source trees.

Imports and paths now refer to this package. The command entry point protects
the recorded results and explains how to obtain a missing dataset.

Device metadata keeps the name needed to join source records, the block,
and terrain position. Probe metadata keeps only routing fields. Neither file
contains device EUIs, coordinates, labels, or unrelated source channels.

## Recorded evidence

The eight aggregate artifacts in `results/checkpoint-2026-11-04/` retain their
original bytes. Their implementation commit names the original qualified code.
Keep that field unchanged. It does not describe a run under this new layout.
New reproductions write their own source and model hashes under `runs/`.

The original preparation record captured a local channel inventory. This
checkout tracks the routing fields that the code needs from that inventory.
The large source CSV, models, and derived data stay outside Git.

Our repository guide and native Google Doc include the full eligibility
discussion and reproduction commands for this package. We revised their prose
for the instructor in our group voice after preparing the repository.

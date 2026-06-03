# Parser Selection: HTML-Native vs. Docling

## Context

finsight ingests SEC 10-K filings, which EDGAR serves as inline-XBRL XHTML —
already-digital text with financial data woven in as XBRL tags. The ingestion
layer converts these into clean, structured text for chunking and embedding,
preserving two things: the financial tables (for numeric questions) and the
Item-based section structure (for prose questions).

The original plan assumed a choice between Docling (open-source, local, ML-based)
and LlamaParse (paid, cloud, OCR-grade). That framing fits scanned PDFs, where
structure must be recovered from images. It does not fit inline-XBRL XHTML, where
the structure is already present in the markup. This reframed the decision toward
a third option — parsing the HTML structurally — and prompted a direct comparison
on the actual corpus rather than an assumption.

LlamaParse was excluded before testing: its advantage is OCR on degraded
documents, which clean XHTML does not require, and its per-page pricing recurs on
every re-parse — a poor fit for the iterative chunking work that follows.

## What was tested

Two parsers, three representative filings:

- **Docling** (`docling`) — IBM's ML document converter, exported to Markdown.
- **selectolax** (`selectolax`) — a fast HTML5 parser; text extraction plus
  structural serialization of `<table>` elements.

| Filing | Why chosen |
|---|---|
| Apple FY2024 (1.5 MB) | Clean, modern baseline both should handle |
| JPMorgan FY2020 (16.9 MB) | Largest, most table-dense filing; fidelity + scale test |
| NVIDIA FY2024 (2.1 MB) | January fiscal-end, heavy XBRL tagging; edge case |

## Results

| Filing | Parser | Time | Output size | Tables |
|---|---|---|---|---|
| Apple FY2024 | selectolax | 0.0 s | 268 K chars | 63 |
| Apple FY2024 | Docling | 2.3 s | 479 K chars | ~773 rows |
| JPMorgan FY2020 | selectolax | 0.5 s | 1.9 M chars | 664 |
| JPMorgan FY2020 | Docling | 22.7 s | 5.1 M chars | ~6,755 rows |
| NVIDIA FY2024 | selectolax | 0.1 s | 409 K chars | 66 |
| NVIDIA FY2024 | Docling | 2.7 s | 930 K chars | ~1,067 rows |

Both parsers completed on all three files, including the 16.9 MB JPMorgan filing.
Docling was roughly 45x slower and produced about twice the text — which
investigation showed was duplication, not richer content.

## Key finding: Docling corrupts inline-XBRL tables

The decisive difference is table fidelity. On Apple's income statement, selectolax
preserved the structure cleanly — correct row labels, three fiscal-year columns in
order, correct values (with trivial empty-cell noise from spacer columns):

    Total net sales | 391,035 | 383,285 | 394,328
    Net income      |  93,736 |  96,995 |  99,803

Docling garbled the same table: it triplicated row labels across merged header
columns, duplicated every value, and exploded the table into ~20 phantom columns
of empty cells and stray percentage fragments:

    | Total net sales | Total net sales | Total net sales | $ | 391,035 | | | | 2 | 2 | % | ...

Docling's ML table reconstruction, designed to recover layout from images, was
confused by the dual display/tagged representation inherent in inline-XBRL. The 2x
output size is explained by this duplication. The result is markup an LLM would
struggle to read a clean figure from.

Section structure was a tie: both parsers preserved the Item 1A / Item 7 / Item 8
headings cleanly. With selectolax these survive as plain-text markers at known
positions, making section segmentation straightforward, controllable code.

## Decision

**Use a HTML-native parser (selectolax).** It produced clean, recoverable tables
and section markers, at a fraction of the time and dependency weight, on the exact
input the system handles. Docling's ML machinery solved a problem this corpus does
not pose and actively degraded table quality on it.

## Consequences

- **We own section detection and table cleaning** — explicit, testable code rather
  than a library's opaque output. Appropriate for a known, homogeneous document
  type, and aligned with owning the ingestion layer.
- **Zero heavyweight dependencies.** No torch, no model weights. The container stays
  light; the project is reproducible by cloning and running, with no API keys or
  model downloads.
- **Docling was removed** from the `ingestion` dependency group after losing the
  comparison; an unused ~1 GB dependency would be dead weight.
- **The parser is built behind a format-agnostic interface.** Supporting a new
  document type (e.g. PDF) later means implementing one more parser against the same
  interface, with no change to chunking, embedding, retrieval, or the API. The
  interface — not any specific parser — is what makes the system extensible.

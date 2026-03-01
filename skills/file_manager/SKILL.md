---
name: file_manager
description: Watch files/URLs, download content on a schedule, index into vector store, and answer questions using RAG.
version: "0.1.0"
llm_provider: null

actions:
  watch:
    description: Add a local file path or URL to the watch list.
    parameters:
      path_or_url:
        type: string
        required: true
        description: Absolute file path or HTTP/S URL to watch.
      label:
        type: string
        description: Human-readable label for this file (used in search results).
      sync_interval_minutes:
        type: integer
        default: 60
        description: How often to re-download/re-index (for URLs). Use 0 to index once.

  unwatch:
    description: Remove a file/URL from the watch list.
    parameters:
      label_or_path:
        type: string
        required: true
        description: Label or path used when the file was added.

  search:
    description: Semantic search across all indexed file contents.
    parameters:
      query:
        type: string
        required: true
        description: Natural-language question or keywords to search for.
      limit:
        type: integer
        default: 5
        description: Maximum number of relevant passages to return.

  list_watched:
    description: List all currently watched files and URLs.
    parameters: {}
---

# File Manager Skill  *(not yet implemented)*

Monitors files and URLs, downloads them on a schedule, indexes their content
into ChromaDB, and answers questions about them using RAG (retrieval-augmented
generation).

## Planned use cases

- **Document memory**: "Remember this PDF and tell me about it later"
- **Periodic sync**: "Check this RSS feed every hour and notify me of new items"
- **Daily file scans**: Index project files so the agent can answer
  "where is the function that handles login?"
- **Web clipping**: "Watch this documentation page for changes"

## When to use *(once implemented)*

- User says "remember this file / URL"
- User says "what does my notes file say about X?"
- User says "find the document that mentions Y"

## Implementation notes (for developers)

- Use `watchdog` for local file monitoring
- Use `httpx` for URL downloads; respect `Last-Modified` / `ETag` headers
- Chunk text (≈500 tokens) before inserting into ChromaDB `files` collection
- Store `{label, path_or_url, last_modified, chunk_index}` as chunk metadata
- On `search`: query ChromaDB → return top-k passages → optionally summarize with LLM
- Scheduled downloads: register a periodic APScheduler job per watched URL

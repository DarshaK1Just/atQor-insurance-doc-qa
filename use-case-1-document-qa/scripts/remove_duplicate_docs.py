"""Remove duplicate documents from Azure AI Search and status.json.

A "duplicate" is any doc_name that has more than one distinct doc_id in the
search index. For each such name, the script keeps the newest doc_id (by
upload_ts stored in the chunk) and deletes all chunk documents for the older
doc_ids. It also removes the stale records from data/status.json.

Usage (from the project root with the venv active):
    python scripts/remove_duplicate_docs.py [--dry-run]

Flags:
    --dry-run   Print what would be deleted without actually deleting anything.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow running from project root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from azure.search.documents import SearchClient

from src.core.azure_clients import search_client as _make_search_client
from src.core.config import get_settings


def collect_doc_ids(client: SearchClient) -> dict[str, list[dict]]:
    """Return {doc_name: [{doc_id, upload_ts, chunk_ids[]}, ...]} from the index."""
    print("Scanning index for all chunks (this may take a moment)…")
    docs: dict[str, dict[str, dict]] = defaultdict(dict)  # name → {id → info}

    results = client.search(
        search_text="*",
        select=["chunk_id", "doc_id", "doc_name", "upload_ts"],
        top=1000,
    )
    page = 0
    count = 0
    while True:
        batch = list(results)
        if not batch:
            break
        for r in batch:
            name = r.get("doc_name") or ""
            doc_id = r.get("doc_id") or ""
            chunk_id = r.get("chunk_id") or ""
            ts = r.get("upload_ts") or ""
            if name and doc_id:
                entry = docs[name].setdefault(doc_id, {"doc_id": doc_id, "upload_ts": ts, "chunks": []})
                if chunk_id:
                    entry["chunks"].append(chunk_id)
            count += 1
        page += 1
        # Azure Search returns at most 1000 per call; use continuation via skip
        try:
            results = client.search(
                search_text="*",
                select=["chunk_id", "doc_id", "doc_name", "upload_ts"],
                top=1000,
                skip=page * 1000,
            )
        except Exception:
            break
        if len(batch) < 1000:
            break

    print(f"  Scanned {count} chunks across {len(docs)} unique document names.")
    return {name: list(id_map.values()) for name, id_map in docs.items()}


def find_duplicates(docs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Return only names that have >1 doc_id (i.e. real duplicates)."""
    return {name: entries for name, entries in docs.items() if len(entries) > 1}


def pick_keepers(entries: list[dict]) -> tuple[dict, list[dict]]:
    """Return (keeper, [to_delete]). Keeper = newest by upload_ts."""
    sorted_entries = sorted(entries, key=lambda e: e.get("upload_ts") or "", reverse=True)
    return sorted_entries[0], sorted_entries[1:]


def delete_chunks(client: SearchClient, chunk_ids: list[str], dry_run: bool) -> int:
    if not chunk_ids:
        return 0
    if dry_run:
        print(f"    [dry-run] would delete {len(chunk_ids)} chunk(s)")
        return len(chunk_ids)
    # Delete in batches of 1000 (Azure Search batch limit)
    deleted = 0
    for i in range(0, len(chunk_ids), 1000):
        batch = [{"chunk_id": cid} for cid in chunk_ids[i:i + 1000]]
        client.delete_documents(documents=batch)
        deleted += len(batch)
    return deleted


def clean_status_json(stale_doc_ids: set[str], dry_run: bool) -> int:
    status_path = get_settings().data_dir / "status.json"
    if not status_path.exists():
        return 0
    data = json.loads(status_path.read_text(encoding="utf-8"))
    before = len(data)
    cleaned = {k: v for k, v in data.items() if k not in stale_doc_ids}
    removed = before - len(cleaned)
    if removed and not dry_run:
        status_path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    elif removed and dry_run:
        print(f"  [dry-run] would remove {removed} record(s) from status.json")
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be deleted without deleting.")
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    settings = get_settings()
    if not settings.search_endpoint:
        print("ERROR: SEARCH_ENDPOINT is not configured in .env — aborting.")
        sys.exit(1)

    client = _make_search_client()

    all_docs = collect_doc_ids(client)
    duplicates = find_duplicates(all_docs)

    if not duplicates:
        print("\nNo duplicate document names found in the index. Nothing to do.")
        return

    print(f"\nFound {len(duplicates)} document name(s) with duplicates:")
    stale_doc_ids: set[str] = set()
    total_chunks_deleted = 0

    for name, entries in sorted(duplicates.items()):
        keeper, to_delete = pick_keepers(entries)
        print(f"\n  {name!r}")
        print(f"    KEEP   doc_id={keeper['doc_id']}  ts={keeper['upload_ts']}  "
              f"({len(keeper['chunks'])} chunks)")
        for stale in to_delete:
            print(f"    DELETE doc_id={stale['doc_id']}  ts={stale['upload_ts']}  "
                  f"({len(stale['chunks'])} chunks)")
            stale_doc_ids.add(stale["doc_id"])
            chunk_ids = stale["chunks"]
            n = delete_chunks(client, chunk_ids, dry_run)
            total_chunks_deleted += n
            if not dry_run:
                print(f"    → deleted {n} chunk(s) from index")

    removed_status = clean_status_json(stale_doc_ids, dry_run)

    print(f"\n{'[dry-run] ' if dry_run else ''}Summary:")
    print(f"  Stale doc_ids:      {len(stale_doc_ids)}")
    print(f"  Index chunks removed: {total_chunks_deleted}")
    print(f"  status.json records removed: {removed_status}")
    if dry_run:
        print("\nRe-run without --dry-run to apply the changes.")


if __name__ == "__main__":
    main()

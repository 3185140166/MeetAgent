# -*- coding: utf-8 -*-
"""Local review UI for retrieval JSONL datasets.

Usage:
    python -m algorithm_lab.scripts.review_retrieval_dataset \
      --input algorithm_lab/datasets/meeting_retrieval_eval.auto_reviewed_140.jsonl \
      --output algorithm_lab/datasets/meeting_retrieval_eval.review_work.jsonl

The output file is a working copy. On startup, rows from the output file override
rows with the same id from the input file. Each save writes the full current
state to the output JSONL.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class ItemUpdate(BaseModel):
    question: str | None = None
    queries: list[str] | None = None
    relevant_note_ids: list[str] | None = None
    relevant_chunk_ids: list[str] | None = None
    relevant_keywords: list[str] | None = None
    difficulty: str | None = None
    review_status: str | None = None
    reviewer_notes: str | None = None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not row.get("id"):
                raise ValueError(f"Missing id at {path}:{line_no}")
            rows.append(row)
    return rows


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def merge_rows(input_rows: list[dict[str, Any]], output_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output_by_id = {str(row["id"]): row for row in output_rows if row.get("id")}
    input_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in input_rows:
        row_id = str(row["id"])
        input_ids.add(row_id)
        merged.append(output_by_id.get(row_id, row))
    for row in output_rows:
        row_id = str(row.get("id") or "")
        if row_id and row_id not in input_ids:
            merged.append(row)
    return merged


def create_app(input_path: Path, output_path: Path) -> FastAPI:
    app = FastAPI(title="Retrieval Dataset Review")
    lock = threading.Lock()
    input_rows = read_jsonl(input_path)
    output_rows = read_jsonl(output_path)
    rows = merge_rows(input_rows, output_rows)
    index_by_id = {str(row["id"]): idx for idx, row in enumerate(rows)}

    def save_all() -> None:
        write_jsonl_atomic(output_path, rows)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return HTML

    @app.get("/api/items")
    def list_items() -> dict[str, Any]:
        with lock:
            summaries = [
                {
                    "id": row.get("id"),
                    "user_id": row.get("user_id"),
                    "difficulty": row.get("difficulty"),
                    "review_status": row.get("review_status", "needs_review"),
                    "auto_review_status": row.get("auto_review_status", ""),
                    "auto_review_confidence": (row.get("auto_review") or {}).get("confidence"),
                    "question": row.get("question", ""),
                }
                for row in rows
            ]
            counts: dict[str, int] = {}
            auto_counts: dict[str, int] = {}
            for row in rows:
                status = str(row.get("review_status") or "needs_review")
                counts[status] = counts.get(status, 0) + 1
                auto_status = str(row.get("auto_review_status") or "none")
                auto_counts[auto_status] = auto_counts.get(auto_status, 0) + 1
            return {
                "input": str(input_path),
                "output": str(output_path),
                "count": len(rows),
                "counts": counts,
                "auto_counts": auto_counts,
                "items": summaries,
            }

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> dict[str, Any]:
        with lock:
            idx = index_by_id.get(item_id)
            if idx is None:
                raise HTTPException(status_code=404, detail="item not found")
            return rows[idx]

    @app.post("/api/items/{item_id}")
    def update_item(item_id: str, update: ItemUpdate) -> dict[str, Any]:
        with lock:
            idx = index_by_id.get(item_id)
            if idx is None:
                raise HTTPException(status_code=404, detail="item not found")
            row = dict(rows[idx])
            data = update.model_dump(exclude_unset=True)
            for key, value in data.items():
                row[key] = value
            rows[idx] = row
            save_all()
            return {"ok": True, "item": row}

    @app.post("/api/save")
    def save() -> dict[str, Any]:
        with lock:
            save_all()
            return {"ok": True, "output": str(output_path), "count": len(rows)}

    return app


HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Retrieval Dataset Review</title>
  <style>
    :root { color-scheme: light; font-family: Arial, "Microsoft YaHei", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #20242a; }
    header { padding: 10px 16px; background: #111827; color: white; display: flex; gap: 16px; align-items: center; }
    header strong { font-size: 15px; }
    header span { font-size: 12px; color: #cbd5e1; }
    main { display: grid; grid-template-columns: 360px 1fr; height: calc(100vh - 45px); }
    aside { border-right: 1px solid #d8dde6; background: white; overflow: hidden; display: flex; flex-direction: column; }
    .filters { padding: 10px; border-bottom: 1px solid #e5e7eb; display: grid; gap: 8px; }
    .filters input, .filters select { width: 100%; box-sizing: border-box; padding: 7px; border: 1px solid #cbd5e1; border-radius: 6px; }
    .stats { font-size: 12px; color: #4b5563; line-height: 1.5; }
    .list { overflow: auto; }
    .item { padding: 9px 10px; border-bottom: 1px solid #eef1f5; cursor: pointer; }
    .item.active { background: #e8f1ff; }
    .item .meta { font-size: 12px; color: #6b7280; display: flex; gap: 8px; margin-bottom: 4px; }
    .badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 1px 7px; background: #eef2ff; color: #3730a3; font-size: 11px; }
    .badge.warn { background: #fff7ed; color: #9a3412; }
    .badge.bad { background: #fef2f2; color: #991b1b; }
    .badge.good { background: #ecfdf5; color: #065f46; }
    .item .q { font-size: 13px; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    section { overflow: auto; padding: 16px; }
    .panel { max-width: 1100px; margin: 0 auto; display: grid; gap: 12px; }
    .row { display: grid; grid-template-columns: 130px 1fr; gap: 10px; align-items: start; }
    label { font-weight: 600; font-size: 13px; color: #374151; padding-top: 7px; }
    input, select, textarea { box-sizing: border-box; width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; font: inherit; background: white; }
    textarea { resize: vertical; min-height: 74px; line-height: 1.45; }
    textarea.source { min-height: 260px; background: #fbfbfc; }
    .ids textarea { min-height: 50px; }
    .actions { display: flex; gap: 8px; position: sticky; bottom: 0; background: #f6f7f9; padding: 10px 0; }
    button { border: 0; border-radius: 6px; padding: 9px 12px; cursor: pointer; font-weight: 600; }
    button.primary { background: #2563eb; color: white; }
    button.good { background: #059669; color: white; }
    button.bad { background: #dc2626; color: white; }
    button.neutral { background: #e5e7eb; color: #111827; }
    .hint { color: #6b7280; font-size: 12px; }
    .review-box { border: 1px solid #dbe3ef; border-radius: 8px; background: white; padding: 10px; font-size: 13px; line-height: 1.5; }
    .review-grid { display: grid; grid-template-columns: 120px 1fr; gap: 6px 10px; }
    .review-grid .key { color: #64748b; font-weight: 600; }
    .review-grid .value { white-space: pre-wrap; overflow-wrap: anywhere; }
    .empty { color: #6b7280; padding: 20px; }
  </style>
</head>
<body>
  <header>
    <strong>Retrieval Dataset Review</strong>
    <span id="paths"></span>
  </header>
  <main>
    <aside>
      <div class="filters">
        <input id="search" placeholder="Search question / id" />
        <select id="statusFilter">
          <option value="">All statuses</option>
          <option value="auto_accepted">auto_accepted</option>
          <option value="needs_human_review">needs_human_review</option>
          <option value="needs_review">needs_review</option>
          <option value="reviewed">reviewed</option>
          <option value="rejected">rejected</option>
        </select>
        <select id="autoStatusFilter">
          <option value="">All auto review statuses</option>
          <option value="accepted">accepted</option>
          <option value="revised">revised</option>
          <option value="rejected">rejected</option>
          <option value="error">error</option>
        </select>
        <select id="difficultyFilter">
          <option value="">All difficulties</option>
          <option value="easy">easy</option>
          <option value="medium">medium</option>
          <option value="hard">hard</option>
          <option value="multi_evidence">multi_evidence</option>
        </select>
        <div class="stats" id="stats">Loading...</div>
      </div>
      <div class="list" id="list"></div>
    </aside>
    <section>
      <div class="panel" id="editor">
        <div class="empty">Select an item to review.</div>
      </div>
    </section>
  </main>
  <script>
    let items = [];
    let selectedId = null;
    let current = null;

    const $ = (id) => document.getElementById(id);
    const splitLines = (value) => value.split(/\n|,/).map(s => s.trim()).filter(Boolean);
    const joinLines = (value) => Array.isArray(value) ? value.join("\n") : "";

    async function loadList() {
      const res = await fetch("/api/items");
      const data = await res.json();
      items = data.items;
      $("paths").textContent = `input: ${data.input} | output: ${data.output}`;
      const reviewCounts = Object.entries(data.counts).map(([k,v]) => `${k}: ${v}`).join(" | ");
      const autoCounts = Object.entries(data.auto_counts || {}).map(([k,v]) => `auto_${k}: ${v}`).join(" | ");
      $("stats").textContent = `total ${data.count} | ${reviewCounts}` + (autoCounts ? ` | ${autoCounts}` : "");
      renderList();
      if (!selectedId && items.length) selectItem(items[0].id);
    }

    function filteredItems() {
      const q = $("search").value.toLowerCase();
      const status = $("statusFilter").value;
      const autoStatus = $("autoStatusFilter").value;
      const difficulty = $("difficultyFilter").value;
      return items.filter(item => {
        if (status && item.review_status !== status) return false;
        if (autoStatus && item.auto_review_status !== autoStatus) return false;
        if (difficulty && item.difficulty !== difficulty) return false;
        if (q && !`${item.id} ${item.question} ${item.auto_review_status}`.toLowerCase().includes(q)) return false;
        return true;
      });
    }

    function renderList() {
      const list = $("list");
      const rows = filteredItems();
      list.innerHTML = rows.map(item => `
        <div class="item ${item.id === selectedId ? "active" : ""}" onclick="selectItem('${item.id.replaceAll("'", "\\'")}')">
          <div class="meta">
            <span>${item.id}</span>
            <span>${item.difficulty || "-"}</span>
            <span class="${reviewBadgeClass(item.review_status)}">${item.review_status || "needs_review"}</span>
            <span class="${autoBadgeClass(item.auto_review_status)}">${item.auto_review_status || "-"}</span>
          </div>
          <div class="q">${escapeHtml(item.question || "")}</div>
        </div>
      `).join("") || `<div class="empty">No items.</div>`;
    }

    function escapeHtml(text) {
      return String(text).replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[ch]));
    }

    function reviewBadgeClass(status) {
      if (status === "reviewed" || status === "auto_accepted") return "badge good";
      if (status === "rejected") return "badge bad";
      return "badge warn";
    }

    function autoBadgeClass(status) {
      if (status === "accepted") return "badge good";
      if (status === "rejected" || status === "error") return "badge bad";
      if (status === "revised") return "badge warn";
      return "badge";
    }

    async function selectItem(id) {
      selectedId = id;
      renderList();
      const res = await fetch(`/api/items/${encodeURIComponent(id)}`);
      current = await res.json();
      renderEditor();
    }

    function renderEditor() {
      const source = current.source || {};
      const auto = current.auto_review || {};
      $("editor").innerHTML = `
        <div class="row"><label>ID</label><input id="idField" value="${escapeHtml(current.id)}" disabled /></div>
        ${autoReviewHtml(auto, current.auto_review_status)}
        <div class="row"><label>Status</label><select id="review_status">
          ${["auto_accepted","needs_human_review","needs_review","reviewed","rejected"].map(s => `<option value="${s}" ${current.review_status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></div>
        <div class="row"><label>Difficulty</label><select id="difficulty">
          ${["easy","medium","hard","multi_evidence"].map(s => `<option value="${s}" ${current.difficulty === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></div>
        <div class="row"><label>Question</label><textarea id="question">${escapeHtml(current.question || "")}</textarea></div>
        <div class="row ids"><label>Queries</label><textarea id="queries">${escapeHtml(joinLines(current.queries))}</textarea></div>
        <div class="row ids"><label>Chunk IDs</label><textarea id="relevant_chunk_ids">${escapeHtml(joinLines(current.relevant_chunk_ids))}</textarea></div>
        <div class="row ids"><label>Note IDs</label><textarea id="relevant_note_ids">${escapeHtml(joinLines(current.relevant_note_ids))}</textarea></div>
        <div class="row ids"><label>Keywords</label><textarea id="relevant_keywords">${escapeHtml(joinLines(current.relevant_keywords))}</textarea></div>
        <div class="row"><label>Reviewer Notes</label><textarea id="reviewer_notes">${escapeHtml(current.reviewer_notes || "")}</textarea></div>
        <div class="row"><label>Source Meta</label><div class="hint">
          user=${escapeHtml(current.user_id || "")} | title=${escapeHtml(source.title || "")} | time=${escapeHtml(source.create_time || "")}<br/>
          note=${escapeHtml(source.note_id || "")} | chunk=${escapeHtml(source.chunk_id || "")} | chunk_index=${escapeHtml(source.chunk_index ?? "")}
        </div></div>
        ${sourceChunksHtml(source)}
        <div class="row"><label>Source Text</label><textarea class="source" readonly>${escapeHtml(source.text_preview || "")}</textarea></div>
        <div class="actions">
          <button class="good" onclick="saveWithStatus('reviewed')">Save Reviewed</button>
          <button class="bad" onclick="saveWithStatus('rejected')">Reject</button>
          <button class="neutral" onclick="saveWithStatus('needs_human_review')">Needs Human Review</button>
          <button class="neutral" onclick="saveWithStatus('needs_review')">Save Draft</button>
          <button class="primary" onclick="goNext()">Next</button>
        </div>
      `;
    }

    function sourceChunksHtml(source) {
      const chunks = Array.isArray(source.chunks) ? source.chunks : [];
      const requirements = Array.isArray(source.evidence_requirements) ? source.evidence_requirements : [];
      if (!chunks.length && !requirements.length) return "";
      const chunkHtml = chunks.map((chunk, idx) => `
        <div class="review-box" style="margin-bottom:8px">
          <div class="review-grid">
            <div class="key">Chunk ${idx + 1}</div><div class="value">${escapeHtml(chunk.chunk_id || "")}</div>
            <div class="key">Index</div><div class="value">${escapeHtml(chunk.chunk_index ?? "")}</div>
            <div class="key">Text</div><div class="value">${escapeHtml(chunk.text_preview || "")}</div>
          </div>
        </div>
      `).join("");
      const reqHtml = requirements.length ? `
        <div class="review-box">
          <div class="review-grid">
            ${requirements.map(req => `
              <div class="key">${escapeHtml(req.chunk_id || "")}</div>
              <div class="value">${escapeHtml(req.required_fact || "")}</div>
            `).join("")}
          </div>
        </div>
      ` : "";
      return `
        <div class="row"><label>Source Chunks</label><div>${chunkHtml}</div></div>
        ${requirements.length ? `<div class="row"><label>Evidence Map</label>${reqHtml}</div>` : ""}
      `;
    }

    function autoReviewHtml(auto, status) {
      if (!auto || Object.keys(auto).length === 0) return "";
      const originalKeywords = Array.isArray(auto.original_keywords) ? auto.original_keywords.join("，") : "";
      const revisedKeywords = Array.isArray(auto.revised_keywords) ? auto.revised_keywords.join("，") : "";
      return `
        <div class="row"><label>Auto Review</label><div class="review-box">
          <div class="review-grid">
            <div class="key">Status</div><div class="value"><span class="${autoBadgeClass(status)}">${escapeHtml(status || auto.status || "-")}</span></div>
            <div class="key">Model</div><div class="value">${escapeHtml(auto.model || "")}</div>
            <div class="key">Confidence</div><div class="value">${escapeHtml(auto.confidence ?? "")}</div>
            <div class="key">Reason</div><div class="value">${escapeHtml(auto.reason || "")}</div>
            <div class="key">Evidence</div><div class="value">${escapeHtml(auto.evidence_summary || "")}</div>
            <div class="key">Original Q</div><div class="value">${escapeHtml(auto.original_question || "")}</div>
            <div class="key">Original KW</div><div class="value">${escapeHtml(originalKeywords)}</div>
            ${auto.revised_question ? `<div class="key">Revised Q</div><div class="value">${escapeHtml(auto.revised_question || "")}</div>` : ""}
            ${revisedKeywords ? `<div class="key">Revised KW</div><div class="value">${escapeHtml(revisedKeywords)}</div>` : ""}
          </div>
        </div></div>
      `;
    }

    function collect(statusOverride) {
      return {
        question: $("question").value,
        queries: splitLines($("queries").value),
        relevant_chunk_ids: splitLines($("relevant_chunk_ids").value),
        relevant_note_ids: splitLines($("relevant_note_ids").value),
        relevant_keywords: splitLines($("relevant_keywords").value),
        difficulty: $("difficulty").value,
        review_status: statusOverride || $("review_status").value,
        reviewer_notes: $("reviewer_notes").value,
      };
    }

    async function saveWithStatus(status) {
      const res = await fetch(`/api/items/${encodeURIComponent(selectedId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collect(status)),
      });
      const data = await res.json();
      current = data.item;
      await loadList();
      selectedId = current.id;
      renderList();
    }

    function goNext() {
      const rows = filteredItems();
      const idx = rows.findIndex(item => item.id === selectedId);
      if (idx >= 0 && idx + 1 < rows.length) selectItem(rows[idx + 1].id);
    }

    $("search").addEventListener("input", renderList);
    $("statusFilter").addEventListener("change", renderList);
    $("autoStatusFilter").addEventListener("change", renderList);
    $("difficultyFilter").addEventListener("change", renderList);
    loadList();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Review retrieval dataset JSONL in a local web UI")
    parser.add_argument("--input", required=True, help="Draft JSONL path")
    parser.add_argument("--output", required=True, help="Working output JSONL path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open browser automatically")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    app = create_app(input_path, output_path)
    url = f"http://{args.host}:{args.port}"
    print(f"Review UI: {url}")
    print(f"Input : {input_path}")
    print(f"Output: {output_path}")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

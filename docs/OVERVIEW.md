# Overview

1. Capture a source         → Inbox (triage new captures)
2. Triage the capture       → Source Workbench (inspect original + normalized)
3. Extract evidence         → Evidence Ledger (select fragments, anchor them)
4. Resolve entities         → Entity Directory (match/merge mentions → canonical)
5. Form claims              → Claims Ledger (subject-property-value assertions)
6. Compare/contradict       → Compare matrix / Conflict Resolution
7. Review                   → Reviews (formal decisions on evidence/claims)
8. Publish                  → Publishing (snapshot → approve → handoff)

## Details

**Step 1 — Capture a source**
You find a webpage, an X post, or a document you want to research. You click the **Capture** button, paste the URL, and the platform opens it in the dedicated browser, saves a frozen copy (HTML, text, screenshots, extracted tables), and drops it into your **Inbox**. Think of it like bookmarking something for deep study — except the platform saves the *exact* version of the page as it existed at that moment, so even if the page changes or disappears later, you still have the original.

**Step 2 — Triage (the Inbox)**
New captures arrive in the **Inbox** like an email inbox. For each one, you decide: is this worth keeping? Should I assign it to a project? Is there a problem (empty text, duplicate of something I already have, broken capture)? You triage by accepting, rejecting, deferring, or assigning each item. The goal is to filter out noise early so only useful sources move forward.

**Step 3 — Inspect the source (Source Workbench)**
This is the "deep dive" view of a single captured source. You see the original page on one side, the extracted/cleaned text on the other, and a panel where you can highlight specific parts of the page and turn them into **evidence**. Think of it like reading a research paper with a highlighter — you select the important sentences, paragraphs, or data points and save them as individual evidence items, each linked back to the exact spot in the original page.

**Step 4 — Extract evidence (Evidence Ledger)**
Every piece of text or data you highlighted in Step 3 becomes a row in the **Evidence Ledger**. Each row says: what is this evidence, where did it come from (the exact source + page position), what type is it (a quote, a number, a claim, an image), and what's its review status (draft, accepted, rejected). This is your curated collection of facts — the raw material for building arguments.

**Step 5 — Resolve entities (Entity Directory)**
As evidence accumulates, the platform (and you) start identifying **entities** — people, organizations, products, technologies, locations mentioned across multiple sources. The Entity Directory groups all mentions of the same thing together. You decide: is "Weaviate" in source A the same as "weaviate.io" in source B? Should "DataLab" and "DataLab AI" be merged? This is about building a clean, deduplicated list of "who and what" your evidence is about.

**Step 6 — Form claims (Claims Ledger)**
A **claim** is a structured assertion backed by evidence. For example: "Weaviate supports hybrid search" (subject: Weaviate, property: feature, value: hybrid search), backed by evidence from their GitHub README. Claims are where your evidence turns into knowledge. Multiple pieces of evidence can support or refute the same claim. When two sources disagree, you get a **contradiction** that needs resolving.

**Step 7 — Review (Reviews)**
The Reviews page is where formal decisions get made — a human reviewer looks at evidence, entities, and claims and says: "I accept this evidence," "I reject this claim," "This contradiction is resolved." Every decision is logged as an immutable audit trail. This is the quality gate — nothing becomes "official knowledge" without a human signing off on it.

**Step 8 — Publish (Publishing)**
When a project's evidence and claims are reviewed and ready, you create a **publication bundle** — a frozen snapshot of the approved content that can be exported as a research report, a website update, or a handoff package. The snapshot is immutable (it can't be changed after approval), so what you publish is exactly what was reviewed.


**In one sentence:** You capture sources → triage them → highlight the important parts → organize who/what they're about → turn the highlights into structured claims → get human sign-off → publish the approved result.


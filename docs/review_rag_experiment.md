# Review RAG audit and retrieval comparison

This report covers the Malaysia restaurant review files, the prepared corpus, and a second retrieval comparison after the evaluation labels were corrected. It does not replace the canonical OSM restaurant file. `ENABLE_REVIEW_RAG` stays off, so the existing chat API does not read reviews unless that flag is turned on for a process. The default restaurant retriever remains BM25.

## Dataset audit

The folder `data/Malaysia Restaurant Review Datasets` has no license file and no README. The rows are scraped Google and TripAdvisor reviews. Public availability is not permission for unrestricted commercial reuse.

City files, not the concatenated `data_cleaned` copies, are the source. Cleaned files repeat the same reviews and were not indexed.

| Check | Result |
|---|---|
| Google columns | Author, Review, Rating, Restaurant, Location |
| TripAdvisor columns | Author, Title, Review, Rating, Dates, Restaurant |
| Restaurant lists | Restaurant, url. `restaurants_ori.csv` also has a row index. |
| Stable source restaurant ID | Absent. TripAdvisor URLs exist only on the restaurant lists, not on review rows. |
| Encoding | UTF-8 with BOM |
| Ratings | Present. Google text such as `Rated 5.0 out of 5` parses to 1–5. All 361,791 kept rows had a rating in range. |
| Dates | TripAdvisor only, often relative text such as `Reviewed yesterday`. Stored as raw text with `date_status=relative_unreliable`. No date was invented. |
| Coordinates | Absent. Google has a location string. TripAdvisor city comes from the filename. |
| Language | Heuristic only: 346,775 Latin/English, 10,128 Chinese characters, 4,427 Malay function-word hints, 461 unknown. This is not a language-ID model. |

Preparation counts from `data/processed/reviews/quality_report.json`, recounted from `reviews.jsonl`:

| Item | Count |
|---|---|
| Rows read | 371,116 |
| Empty review text | 7,859 |
| Exact duplicates removed | 1,466 |
| Deduplicated rows written | 361,791 |
| Likely duplicates flagged and kept | 11,641 |
| Unique normalized restaurant names | 3,432 |
| Unmatched to a canonical restaurant | 328,475 |
| Name found only outside Kuala Lumpur | 6,730 |
| Unique name inside Kuala Lumpur | 22,297 |
| Street overlap, not attached | 800 |
| Matched review rows | 22,297 |
| Ambiguous branch, not attached | 3,489 |
| Ambiguous or street-overlap rows given a canonical ID | 0 |
| Unique canonical IDs with a matched review | 124 |
| Canonical file rewritten | No |

Matching is exact normalized name plus a Kuala Lumpur location signal. A unique name in that area is attached at confidence 0.7. A shared street word is recorded as `street_overlap_unconfirmed` and is not given a `restaurant_id`. Generic words such as jalan, kuala, and lumpur do not count. If the street does not isolate one row, `match_status` is `ambiguous_branch` and `restaurant_id` stays null. No inferred identity was written back to `data/processed/restaurants.json`.

The 300 rows that used to be `unique_street` were all ABC Bistro Cafe, attached to `MY-OSM-node-5328588221` because that row's address contains Sambanthan and the other same-name row has no address. Those rows, and 500 RSMY rows whose street text matches only one of two addresses, were reviewed as two groups. Confirmed-correct groups: 0. Incorrect groups: 0. Unresolved groups: 2, covering all 800 rows. No accuracy percentage is claimed. Details are in `docs/experiments/identity_match_audit.json` and `docs/experiments/street_overlap_groups.json`. The ABC rating average was removed from `rating_summary.jsonl` because that attachment was not confirmed.

| Sample | What was inspected | Result |
|---|---|---|
| Iketeru, `RV-ade47594fe76e226` | Kuala Lumpur Sentral location, one canonical row | Attached to `MY-OSM-node-4698078717` as a unique name |
| Absolute Thai, `RV-7522d8bb87657612` | Johor Bahru source city | Not attached |
| RSMY, `RV-e7da03627a69d970` | Jalan Medan Tuanku versus Jalan Bunus 6, no house number on the Medan Tuanku row | Unresolved, `restaurant_id` null |
| ABC Bistro Cafe, `RV-b7da7bece477c04d` | House 106, Jalan Tun Sambanthan, plus a same-name row with no address | Unresolved, previous attachment withdrawn |

Aspect labels such as cozy, noisy, delicious, and service are lexicon spans. A nearby `not` marks the span as negated. They are opinions, not verified restaurant facts. Rating summaries include only matched reviews that are not flagged as likely duplicates. An average is marked displayable only when that count is at least five, and the summary says the average is only this dataset.

## Evaluation audit

The first comparison used `data/eval/review_retrieval_cases.jsonl` with 10 cases. Three cases (`cuisine-area`, `exclude-western`, `no-evidence`) had no relevance set. Recall, precision, MRR, and nDCG for those cases were null and were left out of the macro average. They were not zero-recall cases. The other seven cases had labels. Those labels were not a complete manual judgment of every relevant review.

Review IDs (`RV-` plus a hash of source file, author, restaurant, raw rating, and text) and canonical restaurant IDs (`MY-OSM-...`) were mixed in the first scoring path: a restaurant-name label expanded to review IDs, while anchor labels were substrings of review text. The corrected file stores either explicit review IDs or the source restaurant-name field. It does not store canonical restaurant IDs as relevance labels.

| First-run zero or null | What the corpus actually contained | Class |
|---|---|---|
| Chambers exact name, recall 0 | 29 curly-apostrophe `Chamber’s Grill` rows and 703 ASCII `Chambers Grill` rows were both indexed. BM25 returned the ASCII spelling. The label contained only the curly spelling, and the BM25 tokenizer splits that apostrophe into `chamber` and `s`. | Label mismatch. Not missing corpus evidence. |
| Noisy anchor | `RV-19cd66fab9bf6510` (“Bit noisy…”) was indexed and ranked 18, outside K=10. | Retrieval cutoff. |
| Delicious / service / high-rating anchors | The labeled sentences were in the pilot and outside the top 100. `food` is a BM25 stop word, so “delicious food” is mostly the token `delicious`. | Retrieval miss. Evidence was indexed. |
| Mixed Knowhere anchors | Both sentences were indexed. The query is a restaurant name, so other reviews of that restaurant outranked the two labeled sentences. | Incomplete label set and a miss of those two IDs. |
| Constraint cases | No relevance IDs. | Not scored. A raw constraint pass rate was recorded separately. |

The first result file is kept at `docs/experiments/review_retrieval_results_baseline.json`. Precision in that run divided by the shorter of K and the number of returned rows, so a short list could look more precise than it was. Precision@K now divides by K. Empty relevance sets still return null, and the aggregate is still the macro mean of non-null per-query scores, not a pooled count across queries. Reciprocal rank fusion uses `k=60`, sums `1/(60+rank)` once per review ID, drops duplicate IDs, and breaks ties by ID.

## Corrected labels

`data/eval/review_retrieval_cases.jsonl` now has 14 cases on the same 5,991-row pilot. Eleven cases have relevance labels. Three are constraint checks and are not given a recall score. No label was taken from an unverified model answer.

Name labels include every pilot row whose source restaurant name matches, after one or more rows were read. Sentence labels include only reviews whose text was read. Other true matches remain unlabeled, so precision on those cases is a lower bound.

| Category | Relevant labels | Used for a category comparison |
|---|---:|---|
| Exact name | 748 (732 Chambers spellings, 16 Nizza) | Yes |
| Atmosphere | 8 read reviews | Yes |
| Food quality | 5 read reviews | Yes |
| Noise | 3 | No |
| Service | 4 | No |
| Low rating | 4 one-star reviews | No |
| High rating | 3 five-star reviews | No |
| Mixed opinion | 2 | No |
| Chinese | 2, from Chinese spans inside translated Google reviews | No |
| Malay | 2 reviews that use `sedap` | No |
| Insufficient evidence, exclusion, area plus cuisine | 0 relevance labels | Constraint rate only |

A category needs at least five relevance labels before its average is treated as comparable. Chinese and Malay queries were added only where those spans exist in the pilot. The pilot has 65 heuristic Chinese rows and 22 heuristic Malay rows; most of the Chinese rows are translated English with a shorter Chinese span later in the text.

## Index

ChromaDB 1.1.0 and fastembed 0.7.1 are installed in `malaysia-food-copilot/.venv`, not in the shared `final-project` Python. The existing index was not rebuilt or deleted.

| Index | Model | Documents | Notes |
|---|---|---:|---|
| `data/vector_store/restaurant_reviews` | Chroma default ONNX `all-MiniLM-L6-v2` | 5,991 | Unchanged. Cosine. About 28.8 MB. |
| `data/vector_store/restaurant_reviews_multilingual_minilm` | fastembed `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 5,991 | New directory. Stated model size 0.22 GB, dimension 384. Build took about 16 minutes, including the download. |

fastembed 0.7.1 warns that this model now uses mean pooling instead of the earlier CLS embedding. The measured multilingual numbers are for that build, not for a separately pinned CLS checkpoint. `multilingual-e5-large` and the 1 GB mpnet model were not downloaded. The full 361,791-row file was not embedded.

## Comparison

Same 14 cases, same pilot corpus, candidate pool 20, final list 10. Hybrid fuses BM25 with the existing MiniLM index. The multilingual run is a fourth mode on the same queries. Null metrics stay out of the average. p95 is not reported because there are 14 queries. RAGAS was not run.

Overall macro mean, 11 labeled queries:

| Metric | BM25 | MiniLM vector | Hybrid RRF | Multilingual MiniLM |
|---|---:|---:|---:|---:|
| Recall@5 | 0.1427 | 0.0461 | 0.1483 | 0.0006 |
| Recall@10 | 0.2285 | 0.1262 | 0.1887 | 0.0012 |
| Precision@5 | 0.2727 | 0.1091 | 0.2182 | 0.0909 |
| Precision@10 | 0.2455 | 0.1364 | 0.1909 | 0.0909 |
| MRR | 0.4091 | 0.1515 | 0.3636 | 0.0909 |
| nDCG@10 | 0.3443 | 0.1687 | 0.2832 | 0.0909 |
| Raw constraint pass rate | 0.3333 | 0.3333 | 0.3333 | 0.3333 |
| Duplicate restaurant rate | 0.0357 | 0.1071 | 0.0357 | 0.1191 |
| Latency p50 | 905 ms | 1,680 ms | 3,347 ms | 51 ms |
| Latency p95 | unavailable, n=14 | unavailable, n=14 | unavailable, n=14 | unavailable, n=14 |

The overall mean still includes categories with fewer than five labels. The comparable subset is the two exact-name queries, the atmosphere query, and the food-quality query:

| Metric | BM25 | MiniLM vector | Hybrid RRF | Multilingual MiniLM |
|---|---:|---:|---:|---:|
| Recall@5 | 0.1423 | 0.0017 | 0.0955 | 0.0017 |
| Recall@10 | 0.2534 | 0.0972 | 0.1440 | 0.0034 |
| Precision@5 | 0.6000 | 0.2500 | 0.4500 | 0.2500 |
| Precision@10 | 0.5750 | 0.3250 | 0.4250 | 0.2500 |
| MRR | 0.6250 | 0.2917 | 0.6250 | 0.2500 |
| nDCG@10 | 0.5926 | 0.3126 | 0.4525 | 0.2500 |

Exact-name recall@10 looks small because Chambers has 732 relevant reviews and only 10 can be returned. Precision is the useful name metric. BM25 precision@10 is 1.0 for both Chambers and Nizza. MiniLM and the multilingual model miss Nizza. Hybrid precision@10 on Nizza is 0.5.

| Case | BM25 | MiniLM | Hybrid | Multilingual | Failure class |
|---|---|---|---|---|---|
| Chambers name | P@10 1.00, retrieved | P@10 1.00, retrieved | P@10 1.00, retrieved | P@10 1.00, retrieved | Retrieved. The old zero came from the curly-apostrophe label. |
| Nizza name | P@10 1.00, R@10 0.625 | miss | P@10 0.50, R@10 0.313 | miss | Vector miss. The 16 rows are in the corpus. |
| Cozy | R@10 0.375, MRR 0.50 | R@10 0.375, MRR 0.17 | R@10 0.25, MRR 1.00 | miss | Retrieved by the first three. Unlabeled cozy reviews make precision a lower bound. |
| Delicious food | miss | miss | miss | miss | Retrieval miss. Five read reviews are in the corpus. `food` is a stop word. |
| Noisy, service, high rating, mixed, Chinese | miss | miss | miss | miss | Evidence is in the corpus. These categories have fewer than five labels. |
| Low rating | R@10 0.50 | miss | R@10 0.50 | miss | Four labels. Not used to rank methods. |
| Malay `sedap` | R@10 1.00 | R@10 1.00 | R@10 1.00 | miss | Two labels. The multilingual model did not retrieve them. |

Raw top-10 constraint pass rate is 0.3333 for every mode because three checks are averaged: Kulim is 1.0 after the filter rejects every hit, and both Western checks are 0.0 on the unfiltered ranking. That is a constraint-filtering result. It is not a relevance score, and it is not an answer-generation result. The hard filter used by the optional review path rejects a Japanese-only canonical row for a Western query; that behavior is covered by unit tests. No answer text was judged in this run.

## Recommendation

Do not switch the default retriever and do not enable review RAG by default. On the corrected set, BM25 has the highest recall@10 and precision@10 in both the overall macro mean and the four-case comparable subset. Hybrid matches BM25 MRR on that subset and is lower on recall@10, precision@10, and nDCG@10. The multilingual MiniLM index is faster per query here and retrieves Chambers, but it misses the other labeled cases, including the two Chinese spans and the two Malay `sedap` reviews. That is not an improvement.

Keep review evidence separate from canonical cards. Do not display a rating average for a restaurant with fewer than five matched, deduplicated reviews. Do not use one branch's review as proof for another branch.

## Food-quality retrieval

The labeled query is `delicious food`. Review BM25 does not drop stop words, so both tokens are scored. In the 5,991-row pilot, `delicious` occurs in 545 reviews and `food` in 2,700. All five labeled Positano reviews contain `delicious` and are present. Their BM25 ranks are 286, 369, 396, 402, and 455. The existing MiniLM ranks are 2461 through 3367. The multilingual MiniLM ranks are 1246 through 3451. None of those ranks is inside the hybrid candidate pool of 20, so hybrid RRF at K=10 also misses them.

The BM25 top 20 are short reviews whose text is essentially “delicious food.” Recall@10 and nDCG@10 on the five labels are 0. MRR is 0.0035. That is an incomplete label set plus length normalization, not a missing-corpus failure.

One change was tried at a time on the same labels. None is adopted.

| Change | Recall@10 | Precision@10 | MRR | nDCG@10 | Latency | What happened |
|---|---:|---:|---:|---:|---:|---|
| Baseline k1=1.5, b=0.75 | 0 | 0 | 0.0035 | 0 | 1,447 ms | Top 10 all contain delicious |
| Query expansion `delicious tasty food` | 0 | 0 | 0.0023 | 0 | 1,471 ms | Three of the top 10 do not contain delicious |
| b=0, no length penalty | 0 | 0 | 0.0667 | 0 | 1,690 ms | Best labeled rank is still outside 10 |
| k1=1.2, b=0.5 | 0 | 0 | 0.0050 | 0 | 1,623 ms | Top 10 still the short delicious reviews |
| Drop the token `food` | 0 | 0 | 0.0034 | 0 | 1,591 ms | Same pattern as the baseline |

Numbers are in `docs/experiments/food_quality_diagnosis.json`. The default ranker is unchanged.

## Grounded answers

Retrieval scores above are separate from answer checks. `data/eval/review_answer_cases.jsonl` has nine hand-written answers. The checker in `src/food_copilot/reviews/faithfulness.py` fails a claim that is missing from the evidence, cites the wrong `restaurant_id`, uses an ambiguous or unconfirmed branch, flips a negative or mixed review into a positive claim, or states an opinion as a fact. Abstention is required when the fixture says evidence is missing, the area is unsupported, or the branch is ambiguous. All nine fixtures match their expected failure lists.

The optional quote path, still off unless `ENABLE_REVIEW_RAG` is set, now quotes only `unique_name_in_area` rows and keeps the words after a lexicon hit, so “delicious but … salty” is not cut down to “delicious.” An ambiguous branch produces: “Review evidence does not identify one canonical branch, so no review was attached.” No model-generated answer was used as ground truth.

## Commands

From `d:\project1\malaysia-food-copilot`:

```text
d:\project1\final-project\.python\python.exe scripts\prepare_reviews.py
.venv\Scripts\python.exe scripts\index_reviews.py
.venv\Scripts\python.exe scripts\index_multilingual_reviews.py
.venv\Scripts\python.exe scripts\evaluate_review_retrieval.py
d:\project1\final-project\.python\python.exe -m pytest tests/unit -q
```

`scripts/index_reviews.py --rebuild` renames the existing MiniLM directory and was not run. `--corpus reviews` would embed all 361,791 rows and was not run. The multilingual script writes only `restaurant_reviews_multilingual_minilm`.

Frontend, from `frontend` with the portable Node on `PATH`:

```text
npm test
npm run build
```

## Tests

Portable Python unit suite: 134 passed, 1 skipped. The skipped test imports Chroma, which is only in `.venv`. The suite covers Western constraints rejecting a Japanese-only row, excluded cuisines, the Kulim limitation sentence, ambiguous branches and street overlaps staying unattached, likely-duplicate reviews staying out of the rating average, empty relevance labels returning null, precision@K dividing by K, RRF ranking a shared ID once, session exclusion not leaking into the next call, mixed quotes keeping the complaint, the nine answer fixtures, and `ENABLE_REVIEW_RAG` defaulting off.

Frontend: 7 tests passed. Production build succeeded (`dist/assets/index-cZkJVb8d.js`).

This pass regenerated `data/processed/reviews/reviews.jsonl`, `pilot_corpus.jsonl`, `rating_summary.jsonl`, and `quality_report.json`. It did not rebuild either vector index, did not embed the full review file, and did not modify `data/processed/restaurants.json`.

## Remaining limits

- Most reviews do not match a canonical OSM restaurant. The two street-overlap groups remain unresolved; house numbers are not in the canonical addresses.
- Relative TripAdvisor dates are not real dates.
- The vector indexes cover 5,991 KL pilot rows, not the full prepared file. Those indexes were not rebuilt after the identity change. The changed rows are not in the pilot name list.
- Noise, service, rating, mixed, Chinese, and Malay categories do not have enough labels for a category winner.
- Exact-name labels were completed from the source name field. Only a sample of those reviews was read.
- The five food-quality labels are long reviews buried under 545 other `delicious` reviews. No ranker change brought them into the top 10 without a reason to replace the baseline.
- The answer fixtures cover nine hand-written cases. They do not score live chat answers.
- fastembed 0.7.1 mean pooling may differ from the original CLS checkpoint of the multilingual model.
- The review text cannot be treated as licensed for commercial redistribution.

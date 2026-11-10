# Sales inquiry business review

From the repository root, run both frozen `p0-02.v2` modes into separate `rule_only` and `mocked_model` directories under one batch directory. Run this companion tool in the same Python environment:

```sh
python scripts/business_review_pack.py data/runtime/batch data/runtime/review-pack
```

Each evidence record binds a customer turn and its history to exact handbook spans, retrieved and supplied chunk IDs, actual reply, CRM facts with source turns, frozen checks, standard revision and replay manifest. The candidate standard keeps AB10 and AB16's original labels alongside the proposed interpretation of the expired offer. Only the listed AB07 child-discount scope has user confirmation.

Sort the queue by group, turn or review dimension. To record a judgment, provide a JSON array of objects containing `evidence_id`, `dimension` (answer_content, grounding or clarification), `grade` (pass, partial or fail), `reason` and `reviewer`. A failure can include `cause` for reporting. Use `--ratings file.json` for each reviewer and choose a new output directory. Conflicting grades remain in the queue with both rationales until adjudicated. Pass a JSON array with --resolutions containing the same identity and grade fields plus reviewed_opinions listing every original reviewer. The packet retains each original judgment and the adjudication rationale. Unknown IDs, duplicated grades or empty rationales are rejected. Keep review packets locally under the ignored runtime directory.

Timing is the wall-clock time to assemble the entire batch from sealed reports and render the local outputs. The replay itself and human review are outside those measurements. The evidence packet lets a reviewer access the materials for a turn in one record. The business review supplements the frozen protocol and does not publish a release gate.


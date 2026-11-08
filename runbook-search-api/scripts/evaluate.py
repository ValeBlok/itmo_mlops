import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.search import SearchEngine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--eval", type=Path, default=Path("data/eval.json"))
    parser.add_argument("--ranking-mode", choices=["normal", "reverse"], default="normal")
    parser.add_argument("--min-mrr", type=float, default=0.85)
    parser.add_argument("--min-recall-at-3", type=float, default=0.90)
    parser.add_argument("--output", type=Path, help="write the JSON quality report to this file")
    args = parser.parse_args()

    engine = SearchEngine(args.artifact_dir, args.ranking_mode)
    cases = json.loads(args.eval.read_text())
    reciprocal_ranks = []
    recalled = 0
    details = []
    for case in cases:
        ids = [item["id"] for item in engine.search(case["query"], 3)]
        ranks = [ids.index(doc_id) + 1 for doc_id in case["relevant"] if doc_id in ids]
        reciprocal_ranks.append(1 / min(ranks) if ranks else 0.0)
        recalled += int(bool(ranks))
        details.append({"query": case["query"], "top3": ids, "relevant": case["relevant"]})

    report = {
        "ranking_mode": args.ranking_mode,
        "index_version": engine.metadata["index_version"],
        "mrr": round(sum(reciprocal_ranks) / len(cases), 4),
        "recall_at_3": round(recalled / len(cases), 4),
        "thresholds": {"mrr": args.min_mrr, "recall_at_3": args.min_recall_at_3},
        "cases": details,
    }
    report["passed"] = report["mrr"] >= args.min_mrr and report["recall_at_3"] >= args.min_recall_at_3
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    if not report["passed"]:
        raise SystemExit(
            f"quality gate failed: mrr={report['mrr']} (min {args.min_mrr}), "
            f"recall@3={report['recall_at_3']} (min {args.min_recall_at_3})"
        )


if __name__ == "__main__":
    main()

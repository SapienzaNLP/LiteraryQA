import json
from pathlib import Path

from tap import Tap

from literaryqa.ngram_metrics import exact_match_score, f1_score, meteor_score, rouge_l_score


class ScriptArgs(Tap):
    predictions_file: Path  # Path to the predictions JSONL file
    output_file: Path | None = None  # Path to save the computed metrics


def main(args: ScriptArgs) -> None:
    # Load predictions
    with args.predictions_file.open("r", encoding="utf-8") as f:
        predictions_data = [json.loads(line) for line in f]

    # Check schema of predictions_data
    for item in predictions_data:
        if "prediction" not in item or "answers" not in item:
            raise ValueError("Each item in predictions file must contain 'prediction' and 'answers' fields.")
        if not isinstance(item["answers"], list):
            raise ValueError("'answers' field must be a list of reference answers.")

    # Extract predictions and references
    predictions = [item["prediction"] for item in predictions_data]
    references = [item["answers"] for item in predictions_data]

    # Compute metrics
    em = exact_match_score(predictions, references)
    f1 = f1_score(predictions, references)
    rouge_l = rouge_l_score(predictions, references)
    meteor = meteor_score(predictions, references)

    metrics = {
        "exact_match": em,
        "f1": f1,
        "rouge_l": rouge_l,
        "meteor": meteor,
    }

    # Output results
    if args.output_file:
        with args.output_file.open("w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=4)
    else:
        print(json.dumps(metrics, indent=4))


if __name__ == "__main__":
    args = ScriptArgs().parse_args()
    main(args)

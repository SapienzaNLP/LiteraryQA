"""LiteraryQA evaluation metrics."""

import importlib.metadata as importlib_metadata
import re
import string
from collections import Counter

import nltk
import numpy as np
from nltk.translate import meteor_score as nltk_meteor_score
from packaging import version
from rouge_score import rouge_scorer, scoring

### Exact Match and word-level F1 as implemented in HotpotQA
# https://raw.githubusercontent.com/hotpotqa/hotpot/refs/heads/master/hotpot_evaluate_v1.py


def normalize_answer(s: str) -> str:
    """Lower text and remove punctuation, articles and extra whitespace."""

    def remove_articles(text: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text: str) -> str:
        return " ".join(text.split())

    def remove_punc(text: str) -> str:
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)

    def lower(text: str) -> str:
        return text.lower()

    return white_space_fix(remove_articles(remove_punc(lower(s))))


def f1_score(predictions: list[str], references: list[list[str]]) -> float:
    """Compute the token-level F1 score between prediction and ground truth."""

    def f1(prediction: str, ground_truth: str) -> tuple[float, float, float]:
        normalized_prediction = normalize_answer(prediction)
        normalized_ground_truth = normalize_answer(ground_truth)

        ZERO_METRIC = (0, 0, 0)

        if normalized_prediction in ["yes", "no", "noanswer"] and normalized_prediction != normalized_ground_truth:
            return ZERO_METRIC
        if normalized_ground_truth in ["yes", "no", "noanswer"] and normalized_prediction != normalized_ground_truth:
            return ZERO_METRIC

        prediction_tokens = normalized_prediction.split()
        ground_truth_tokens = normalized_ground_truth.split()
        common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
        num_same = sum(common.values())
        if num_same == 0:
            return ZERO_METRIC
        precision = 1.0 * num_same / len(prediction_tokens)
        recall = 1.0 * num_same / len(ground_truth_tokens)
        f1 = (2 * precision * recall) / (precision + recall)
        return f1, precision, recall

    total_f1 = 0
    for pred, truths in zip(predictions, references):
        f1s = [f1(pred, truth)[0] for truth in truths]
        total_f1 += max(f1s)
    return total_f1 / len(predictions)


def exact_match_score(predictions: list[str], references: list[list[str]]) -> float:
    """Compute the Exact Match (EM) score between prediction and ground truth."""

    def em(pred: str, truths: list[str]) -> int:
        for truth in truths:
            if normalize_answer(pred) == normalize_answer(truth):
                return 1
        return 0

    total_em = 0
    for pred, truths in zip(predictions, references):
        total_em += em(pred, truths)
    return total_em / len(predictions)


### ROUGE-L metric implementation
# https://github.com/google-research/google-research/blob/master/rouge


def rouge(
    predictions: list[str],
    references: list[list[str]],
    rouge_types: list[str] | None = None,
    use_aggregator: bool = True,
    use_stemmer: bool = False,
) -> dict[str, float]:
    """Compute ROUGE scores between predictions and references."""
    if rouge_types is None:
        rouge_types = ["rouge1", "rouge2", "rougeL", "rougeLsum"]

    scorer = rouge_scorer.RougeScorer(rouge_types=rouge_types, use_stemmer=use_stemmer)
    if use_aggregator:
        aggregator = scoring.BootstrapAggregator()
    else:
        scores = []

    for ref, pred in zip(references, predictions):
        score = scorer.score_multi(ref, pred)
        if use_aggregator:
            aggregator.add_scores(score)
        else:
            scores.append(score)

    if use_aggregator:
        result = aggregator.aggregate()
        for key in result:
            result[key] = result[key].mid.fmeasure
    else:
        result = {}
        for key in scores[0]:
            result[key] = list(score[key].fmeasure for score in scores)

    return result


def rouge_l_score(
    predictions: list[str],
    references: list[list[str]],
    use_stemmer: bool = False,
) -> float:
    """Compute ROUGE-L scores between predictions and references."""
    rouge_result = rouge(
        predictions,
        references,
        rouge_types=["rougeL"],
        use_aggregator=True,
        use_stemmer=use_stemmer,
    )
    return np.mean(rouge_result["rougeL"]).item()


### METEOR metric implementation


def meteor_score(
    predictions: list[str], references: list[list[str]], alpha: float = 0.9, beta: int = 3, gamma: float = 0.5
) -> float:
    """Compute METEOR scores between predictions and references."""
    NLTK_VERSION = version.parse(importlib_metadata.version("nltk"))

    # Ensure required NLTK resources are downloaded
    try:
        nltk.data.find("corpora/wordnet")
    except LookupError:
        nltk.download("wordnet")

    if NLTK_VERSION >= version.Version("3.6.4"):
        from nltk import word_tokenize
    else:
        raise ImportError("nltk>=3.6.4 is required for METEOR metric")

    if NLTK_VERSION >= version.Version("3.6.5"):
        # the version of METEOR in NLTK version 3.6.5 and earlier expect tokenized inputs
        scores = [
            nltk_meteor_score.meteor_score(
                [word_tokenize(ref) for ref in refs],
                word_tokenize(pred),
                alpha=alpha,
                beta=beta,
                gamma=gamma,
            )
            for refs, pred in zip(references, predictions)
        ]
    else:
        scores = [
            nltk_meteor_score.meteor_score(
                [[word_tokenize(ref) for ref in group] for group in references][0],
                word_tokenize(pred),
                alpha=alpha,
                beta=beta,
                gamma=gamma,
            )
            for ref, pred in zip(references, predictions)
        ]

    return np.mean(scores).item()

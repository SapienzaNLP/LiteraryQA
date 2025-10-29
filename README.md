<div align="center"><img src="assets/literaryqa_icon.png" width="700"></div>

<div align="center">

[![Conference](http://img.shields.io/badge/EMNLP-2025-4b44ce.svg)](https://2025.aclweb.org/)
[![Paper](http://img.shields.io/badge/paper-ACL--anthology-B31B1B.svg)](https://arxiv.org/abs/2510.13494)
[![arXiv](https://img.shields.io/badge/arXiv-paper-008080.svg)](https://arxiv.org/abs/2510.13494) 
[![Hugging Face Dataset](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Dataset-FCD21D)](https://huggingface.co/datasets/sapienzanlp/LiteraryQA)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-green.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
</div>


##  📖 Description
LiteraryQA is a long-context question-answering benchmark focusing on literary works.
We derived this dataset from [NarrativeQA](https://arxiv.org/abs/1712.07040), addressing issues with the raw text of books, with the crowdsourced QAs, and with the metrics employed to evaluate systems on this kind of benchmarks.

For further details, please refer to our EMNLP 2025 main conference paper: [LiteraryQA: Towards Effective Evaluation of Long-document Narrative QA](https://arxiv.org/abs/2510.13494) by [Tommaso Bonomo](https://www.linkedin.com/in/tommaso-bonomo/)\*, [Luca Gioffré](https://www.linkedin.com/in/luca-gioffre/)\* and [Roberto Navigli](https://www.linkedin.com/in/robertonavigli/).

This dataset is available on [🤗 Hugging Face](https://huggingface.co/datasets/sapienzanlp/LiteraryQA).
If you rather download the data manually, or if you want to run evaluations on your own models' predictions, please follow the instructions below.

## ⚠️ Project Gutenberg License Disclaimer

LiteraryQA is based on books from Project Gutenberg, which are publicly available under the [Project Gutenberg License](https://www.gutenberg.org/policy/license.html).
This license holds for users located in the United States, where the books are in the public domain.

We do not distribute the original text of the books, rather our dataset consists of a script that downloads and preprocesses the books from Project Gutenberg.
**Users are responsible for checking the copyright status of each book in their country**.


## 💾 Local data

### ⚙️ Setup and download

Clone the repository:
```bash
git clone https://github.com/sapienzanlp/LiteraryQA.git
cd LiteraryQA
```

We recommend using [uv](https://docs.astral.sh/uv/getting-started/installation/) as your Python package manager to quickly run our scripts.
You can install it with:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

To download and clean the books from Project Gutenberg, run:
```bash
uv run scripts/download_and_clean_books.py

options:
  --output_dir <path> = "data/literaryqa"  # Directory to save downloaded books
  --write_as_jsonl <bool> = False # Whether to write the complete dataset as JSONL files in output_dir/jsonl
```

<details>
<summary>Using <code>venv</code> instead of <code>uv</code></summary>

If you rather use `venv` and `pip`, you can create a virtual environment and install the required packages with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then, you can run the download script with:
```bash
python scripts/download_and_clean_books.py --output_dir data/literaryqa
```
</details>

### 📋 Data format
The dataset is organized with the following schema:
* **`document_id`** *(str)* — Unique NarrativeQA identifier for the document.
* **`gutenberg_id`** *(str)* — Project Gutenberg key identifying the book.
* **`split`** *(str)* — Dataset partition where the book belongs (e.g., `"train"`, `"validation"`, `"test"`).
* **`title`** *(str)* — Title of the book.
* **`text`** *(str)* — Full text of the book from Project Gutenberg.
* **`summary`** *(str)* — Human-written or Wikipedia-derived summary of the book.
* **`qas`** *(list[dict])* — List of question–answer pairs related to the book. Each element contains:

  * **`question`** *(str)* — A question about the book.
  * **`answers`** *(list of str)* — One or more reference answers.
  * **`is_question_modified`** *(bool)* — Whether the question comes from the original NarrativeQA dataset (`False`) or was edited (`True`)
  * **`is_answer_modified`** *(list of bool)* — For each answer, whether it comes from the original NarrativeQA dataset (`False`) or was edited (`True`)
* **`metadata`** *(dict)* — Additional contextual information about the book, including:

  * **`author`** *(str)* — Name of the book’s author.
  * **`publication_date`** *(str)* — Publication date (or “-” if unknown).
  * **`genre_tags`** *(str)* — Semicolon-separated list of genres or literary classifications.
  * **`text_urls`** *(str)* — URL to the original full text source.
  * **`summary_urls`** *(str)* — URL to the source of the summary.


Here is an example of an entry of the dataset:
```json
{
  "document_id": "9562ea781e95c048df96f528a2a8272721cde3a7",
  "gutenberg_id": "32154",
  "split": "test",
  "title": "The Variable Man",
  "text": "THE VARIABLE MAN\nBY PHILIP K. DICK\nILLUSTRATED BY EBEL\nHe fixed things—clocks, refrigerators, vidsen...",
  "summary": "The Terran system is growing and expanding all the time. But an old and corrupt Centaurian Empire is...",
  "qas": [
    {
      "question": "Why is Terra at war with Proxima Centauri?",
      "answers": [
        "Because they will not give Terra the room to expand their empire.",
        "The Centaurian Empire will not let humans from Terra grow out of their current empire."
      ],
      "is_question_modified": false,
      "is_answer_modified": [false, false]
    }
  ],
  "metadata": {
    "author": "Philip K. Dick",
    "publication_date": "1950",
    "genre_tags": "novella;literary work;sci-fi;",
    "text_urls": "http://www.gutenberg.org/ebooks/32154.txt.utf-8",
    "summary_urls": "http://en.wikipedia.org/wiki/The_Variable_Man"
  }
}
```


## 📊 Evaluation

To run the evaluation of your model's predictions, you must have a file in JSONL format containing the predictions and the reference answers.
Each row in the JSONL file must be a JSON object that conforms to the following schema:
* **`prediction`** *(str)* — The model’s predicted answer to the question.
* **`answers`** *(list of str)* — List of ground-truth (reference) answers for evaluation.
* **`question`** *(str, optional)* — The original question posed to the model; used for context or evaluation by an LLM judge.
* **`title`** *(str, optional)* — Title of the book associated with the question; provides additional context.
* **`summary`** *(str, optional)* — Summary of the book; used in summary-based evaluation settings.

Here is an example (*formatted for clarity*) of a row of the JSONL file:
```json
{
  "prediction": "Terra is hemmed in by the Centauran Empire, cutting it off from other systems.",
  "answers": [
    "Because they will not give Terra the room to expand their empire.",
    "The Centaurian Empire will not let humans from Terra grow out of their current empire."
    ],
  "question": "Why is Terra at war with Proxima Centauri?",
  "title": "The Variable Man",
  "summary": "The Terran system is growing and expanding all the time. But an old and corrupt Centaurian Empire is..."
}
```



We provide the predictions of the systems tested in the paper in the `data/predictions/` folder for your reference.

To run the evaluation, first update the environment to use the necessary packages:
```bash
uv sync --extra judging
```

<details>
<summary>If using <code>pip</code> inside of a virtual environment instead of <code>uv</code></summary>

You can install the extra packages with:
```bash
pip install -e ".[judging]"
```
</details>

Then, use the following command:
```bash
uv run scripts/evaluate_predictions.py --predictions_file <path_to_your_predictions_file>
```


## 📝 Citation
This work has been published at EMNLP 2025 (main conference). If you use any artifact, please cite our paper as follows:

```bibtex
@inproceedings{bonomo-etal-2025-literaryqa,
    title = "{LiteraryQA: Towards Effective Evaluation of Long-Document Narrative QA}",
    author = "Bonomo, Tommaso  and
      Gioffr{\'e}, Luca  and
      Navigli, Roberto",
    editor = "",
    booktitle = "Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing (EMNLP)",
    month = nov,
    year = "2025",
    address = "Suzhou, China",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2025.emnlp-main.xxx",
    doi = "",
    pages = "xxx--xxx",
    abstract = "Question Answering (QA) on narrative text poses a unique challenge to current systems, requiring a deep understanding of long, complex documents. However, the reliability of NarrativeQA, the most widely used benchmark in this domain, is hindered by noisy documents and flawed QA pairs. In this work, we introduce LiteraryQA, a high-quality subset of NarrativeQA focused on literary works. Using a human- and LLM-validated pipeline, we identify and correct low-quality QA samples while removing extraneous text from source documents. We then carry out a meta-evaluation of automatic metrics to clarify how systems should be evaluated on LiteraryQA. This analysis reveals that all n-gram-based metrics have a low system-level correlation to human judgment, while LLM-as-a-Judge evaluations, even with small open-weight models, can strongly agree with the ranking identified by humans. Finally, we benchmark a set of long-context LLMs on LiteraryQA. We release our code and data at https://github.com/SapienzaNLP/LiteraryQA."
}

```


## 📄 License

The data and software are licensed under [Creative Commons Attribution-NonCommercial-ShareAlike 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

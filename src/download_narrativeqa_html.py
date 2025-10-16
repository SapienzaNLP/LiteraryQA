"""Download NarrativeQA documents from Project Gutenberg with robust encoding handling.

This module provides utilities to fetch HTML books referenced by the
NarrativeQA dataset (Hugging Face Hub), attempting multiple Gutenberg mirrors,
detecting file encodings, and fixing common mojibake artifacts. It logs failed
downloads and writes output files into a structured directory.

Key features:
- Load NarrativeQA metadata from a Hugging Face dataset path.
- Extract Gutenberg book IDs from NarrativeQA document URLs.
- Download HTML files from reliable mirrors and cache them on disk.
- Detect encoding with ``chardet`` and optionally fix text with ``ftfy``.
- Track failures and write them to a TSV for follow-up.
"""

import os
import re
import pandas as pd
import requests
from tap import Tap
from tqdm import tqdm
from pathlib import Path
from datasets import load_dataset
from ftfy import fix_text
from src.logging_utils import log, loguru_setup

# from loguru import logger as log
import chardet


# List of mirrors to try if the main site is down
MIRRORS = [
    "https://www.gutenberg.org/files/",
    "http://www.gutenberg.lib.md.us/files/",
    "https://gutenberg.pglaf.org/files/",
    "http://mirrors.xmission.com/gutenberg/files/",
]
SPECIAL_MIRRORS = [
    "http://aleph.gutenberg.org/{subfolders}/{book_id}//{book_id}-h//{book_id}-h.htm",  # original source of QuALITY
    "https://gutenberg.pglaf.org/{subfolders}/{book_id}/{book_id}-h/{book_id}-h.htm",  # most reliable mirror
    "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}-images.html",  # another common pattern
]
MOJIBAKE_PATTERNS = [
    r"Ã.",
    r"â€™",
    r"â€œ",
    r"â€",
    r"ðŸ",  # Common UTF-8 misinterpretations
    r"â€”",
    r"â€¦",
    r"â€“",
    r"â€˜",  # Fancy punctuation errors
]


class ScriptArgs(Tap):
    """Command-line arguments for the downloader script.

    Attributes:
        nqa_hf_path: Hugging Face dataset identifier/path for NarrativeQA.
        output_dir: Base directory where downloads and logs will be stored.
    """

    nqa_hf_path: str = "deepmind/narrativeqa"
    output_dir: Path = Path("data/narrativeqa")
    splits: str = (
        "test"  # dash-separated list of splits to process, e.g. "train-validation-test"
    )

    def process_args(self):
        """Post-parse hook to normalize and prepare arguments.

        Ensures that ``output_dir`` exists before use.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        self.data_splits = self.splits.split("-")
        loguru_setup(level="INFO")


def is_text_corrupted(text):
    """Heuristically detect whether decoded text appears corrupted (mojibake).

    The function searches for a set of common mojibake patterns that indicate
    incorrect UTF-8 decoding. If the ratio of matched characters to the total
    text length exceeds 0.5% (for texts longer than 100 characters), the text
    is considered corrupted and in need of fixing.

    Args:
        text: The decoded text to inspect.

    Returns:
        True if the text likely contains decoding artifacts; False otherwise.
    """
    # Count occurrences of mojibake patterns
    corrupted_matches = sum(
        len(re.findall(pattern, text)) for pattern in MOJIBAKE_PATTERNS
    )
    # If more than 0.5% of characters are corrupted, we apply ftfy
    return (corrupted_matches / len(text)) > 0.005 if len(text) > 100 else False


def detect_encoding_and_read(file_path: Path) -> str:
    """Read text from a file with detected encoding and optionally fix mojibake.

    This function uses ``chardet`` to guess the file encoding, decodes the file
    contents, and then applies a heuristic check. If the text appears to be
    corrupted, it applies ``ftfy.fix_text`` to repair common Unicode issues.

    Args:
        file_path: Path to the text/HTML file on disk.

    Returns:
        The decoded (and possibly fixed) text as a string.
    """
    # Detect encoding
    with open(file_path, "rb") as f:
        raw_data = f.read()
        detected = chardet.detect(raw_data)
        encoding = detected["encoding"] if detected["encoding"] else "utf-8"

    # Read file with detected encoding
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        text = f.read()
    if is_text_corrupted(text):
        text = fix_text(text)
    return text


def download_htm_from_gutenberg(
    book_id: str, save_dir: Path, split: str, pbar: tqdm | None = None
):
    """Download a Gutenberg HTML file for a given book ID, with mirror fallback.

    The function first checks a cached copy under ``save_dir/split/{book_id}.htm``.
    If not present, it tries a list of known Gutenberg mirrors until one
    succeeds, then reads the file using robust encoding detection and mojibake
    fixing. Failures are appended to ``save_dir/logs/failed_downloads.log``.

    Args:
        book_id: Project Gutenberg numeric book identifier as a string.
        save_dir: Base output directory where files and logs are stored.
        split: Dataset split label (e.g., ``"train"``, ``"validation"``, ``"test"``)
            used to organize the download directory.
        pbar: Optional ``tqdm`` progress bar for inline status updates.

    Returns:
        The decoded HTML text if successfully retrieved and read; otherwise
        ``None``.
    """
    log_file = save_dir / "logs" / "failed_downloads.log"
    os.makedirs(log_file.parent, exist_ok=True)

    text = None
    html_file = save_dir / split / f"{book_id}.htm"
    os.makedirs(html_file.parent, exist_ok=True)

    if html_file.exists() and html_file.is_file():
        if pbar:
            pbar.set_description(f"File already exists: {html_file}")
        text = detect_encoding_and_read(html_file)
    else:
        # Try to download the file from the mirrors
        subfolders = "/".join(book_id[0:4])
        urls = [
            url.format(book_id=book_id, subfolders=subfolders)
            for url in SPECIAL_MIRRORS
        ]
        html_url = "{mirror}{book_id}/{book_id}-h.htm"
        urls.extend(
            [html_url.format(mirror=mirror, book_id=book_id) for mirror in MIRRORS]
        )

        for url in urls:
            if pbar:
                pbar.set_description(f">> [{book_id}]: Trying URL: {url}")
            try:
                response = requests.get(url, stream=True, timeout=10)
                if response.status_code == 200:
                    with open(html_file, "wb") as file:
                        for chunk in response.iter_content(1024):
                            file.write(chunk)

                    text = detect_encoding_and_read(html_file)
            except requests.RequestException as e:
                log.warning(f"Failed to download {url}: {e}")
            if text:
                break

        if not text:
            log.error(f"Failed to download {book_id}")
            with open(log_file, "a") as log_file:
                print(book_id, file=log_file)

    return text


def extract_narrativeqa_book_id(url):
    """Extract the Gutenberg book ID from a NarrativeQA document URL.

    NarrativeQA URLs typically end with a filename containing the Gutenberg
    book ID, e.g., ``.../12345-h.htm``. This function parses the URL and
    returns the numeric portion as a string.

    Args:
        url: The NarrativeQA document URL string.

    Returns:
        The extracted book ID as a string if parsing succeeds; ``None`` on
        failure (with a warning printed to stdout).
    """
    try:
        book_id = url.split("/")[-1].split(".")[0].split("-")[0]
        return book_id
    except IndexError:
        log.error(f"Error extracting book ID from URL: {url}")
        return None


def download_narrativeqa_raw_files(
    nqa_hf_path: str, splits: list[str], output_dir: Path
):
    """Load NarrativeQA, download Gutenberg HTMLs, and record failures.

    This function loads the NarrativeQA dataset from Hugging Face, filters to
    Gutenberg-sourced documents, downloads their corresponding HTML files using
    ``download_htm_from_gutenberg``, and accumulates any failures into a Pandas
    DataFrame. The failures are also written to ``output_dir/nqa_failed_download.tsv``.

    Args:
        nqa_hf_path: Hugging Face dataset path for NarrativeQA (e.g.,
            ``"deepmind/narrativeqa"``).
        output_dir: Directory where downloads and summary files will be written.

    Returns:
        A ``pandas.DataFrame`` listing IDs/URLs that could not be downloaded,
        with columns ``id``, ``book_id``, ``split``, and ``url``.
    """
    df = {
        "id": [],
        "book_id": [],
        "split": [],
        "url": [],
    }

    log.info(f"Loading NarrativeQA dataset from {nqa_hf_path}")
    nqa = load_dataset(nqa_hf_path)

    for split in splits:
        log.info(f"Loading split: {split}")
        data = nqa[split]
        samples = set(
            (sample["document"]["id"], sample["document"]["url"])
            for sample in data
            if sample["document"]["kind"].lower() == "gutenberg"
        )
        for sample in (pbar := tqdm(sorted(samples))):
            doc_id, url = sample
            book_id = extract_narrativeqa_book_id(url)
            if book_id is None:
                df["id"].append(doc_id)
                df["book_id"].append("-")
                df["split"].append(split)
                df["url"].append(url)
                continue

            # download the html file
            gutenberg_html = download_htm_from_gutenberg(
                book_id=book_id,
                split=split,
                save_dir=output_dir,
                pbar=pbar,
            )
            if gutenberg_html is None:
                df["id"].append(doc_id)
                df["book_id"].append(book_id)
                df["split"].append(split)
                df["url"].append(url)
                continue

    log.info(f"Loaded {len(data)} samples from {split}")

    df = pd.DataFrame(df)
    filename = output_dir / "nqa_failed_download.tsv"
    df.to_csv(filename, sep="\t", index=False)
    log.info(f"Failed download logged at: {filename}")
    return df


def main(args: ScriptArgs):
    """Entry point for CLI usage.

    Loads NarrativeQA and attempts to download all referenced Gutenberg HTMLs,
    then prints a short summary of failures.

    Args:
        args: Parsed command-line arguments of type ``ScriptArgs``.
    """
    nqa_df = download_narrativeqa_raw_files(
        args.nqa_hf_path, args.data_splits, args.output_dir
    )
    log.info(f"NarrativeQA -- Failed download: {len(nqa_df)} books.")
    print(f"\nNarrativeQA DataFrame - .head():\n{nqa_df.head()}")
    print(f"\nNarrativeQA DataFrame - .describe():\n{nqa_df.describe()}")


if __name__ == "__main__":
    args = ScriptArgs().parse_args()
    main(args)

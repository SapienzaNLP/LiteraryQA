import re
from pathlib import Path

import chardet
import requests
from ftfy import fix_text
from loguru import logger
from tqdm import tqdm

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
    corrupted_matches = sum(len(re.findall(pattern, text)) for pattern in MOJIBAKE_PATTERNS)
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


def download_htm_from_gutenberg(book_id: str, split: str, save_dir: Path, log_dir: Path, pbar: tqdm | None = None):
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
    log_file = log_dir / split / "downloads.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    text = None
    html_file = save_dir / split / f"{book_id}.htm"
    html_file.parent.mkdir(parents=True, exist_ok=True)

    if html_file.exists() and html_file.is_file():
        if pbar:
            pbar.set_description(f"File already exists: {html_file}")
        text = detect_encoding_and_read(html_file)
    else:
        # Try to download the file from the mirrors
        subfolders = "/".join(book_id[0:4])
        urls = [url.format(book_id=book_id, subfolders=subfolders) for url in SPECIAL_MIRRORS]
        html_url = "{mirror}{book_id}/{book_id}-h.htm"
        urls.extend([html_url.format(mirror=mirror, book_id=book_id) for mirror in MIRRORS])

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
                logger.warning(f"Failed to download {url}: {e}")
            if text:
                break

        # Write url to logfile
        with open(log_file, "a") as f:
            if not text:
                f.write(f"{book_id}\tFAILED\tAll mirrors failed\n")
            else:
                f.write(f"{book_id}\tSUCCESS\t{url}\n")

    return text

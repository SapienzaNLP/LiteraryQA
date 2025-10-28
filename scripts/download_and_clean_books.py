"""Download LiteraryQA documents from Project Gutenberg with robust encoding handling, then clean and preprocess the text.

This module provides utilities to fetch HTML books referenced by the NarrativeQA dataset and subsequently kept in LiteraryQA, attempting multiple Gutenberg mirrors, detecting file encodings, and fixing common mojibake artifacts. It logs failed downloads and writes output files into a structured directory.
It also cleans the downloaded HTML files to produce normalized text files suitable for QA tasks. It removes boilerplate (headers/footers, license sections), handles special structures (poems, dialogues), and collects diagnostics about residual Gutenberg markers.
"""

import json
from csv import DictReader, DictWriter
from pathlib import Path

from loguru import logger
from tap import Tap
from tqdm import tqdm

from literaryqa.clean import clean_and_save, detect_encoding_and_read, extract_raw_text
from literaryqa.download import download_htm_from_gutenberg

ANNOTATIONS_FOLDER = Path("data/annotations")


class ScriptArgs(Tap):
    """Command-line arguments for the downloader script."""

    output_dir: Path = Path("data/literaryqa")  # Directory to save downloaded books
    write_as_jsonl: bool = False  # Whether to write the complete dataset as JSONL files

    def process_args(self) -> None:
        """Ensure the output directory exists and setup logging."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logging_dir = self.output_dir / "logs"
        self.logging_dir.mkdir(parents=True, exist_ok=True)


LITERARYQA_URLS = Path("data/literaryqa_urls.tsv")


def main(args: ScriptArgs) -> None:
    """Main function to download and clean books.

    Args:
        args: Parsed command-line arguments.
    """

    logger.info(f"Starting download and cleaning process. Output directory: {args.output_dir}")

    ### Download step ###

    # Load the literaryqa_urls from a predefined source
    literaryqa_urls = {}
    with LITERARYQA_URLS.open("r", encoding="utf-8") as f:
        reader = DictReader(f, delimiter="\t")
        for row in reader:
            lqa_id, book_id, url, split = row["id"], row["book_id"], row["url"], row["split"]
            if split not in literaryqa_urls:
                literaryqa_urls[split] = [(lqa_id, book_id, url)]
            else:
                literaryqa_urls[split].append((lqa_id, book_id, url))
    logger.info("Loaded LiteraryQA URLs.")
    logger.info("Split counts: " + str({k: len(v) for k, v in literaryqa_urls.items()}))
    logger.info("Total books: " + str(sum(len(v) for v in literaryqa_urls.values())))

    # Download each book, handling errors and logging failures
    errors = []
    for split, samples in literaryqa_urls.items():
        logger.info(f"Processing split: {split}")
        for doc_id, book_id, url in (pbar := tqdm(samples, desc=f"Downloading books for {split}")):
            gutenberg_html = download_htm_from_gutenberg(
                book_id=book_id,
                split=split,
                save_dir=args.output_dir,
                log_dir=args.logging_dir,
                pbar=pbar,
            )
            if gutenberg_html is None:
                errors.append({"doc_id": doc_id, "book_id": book_id, "split": split, "url": url})
    logger.info(f"Completed downloads with {len(errors)} errors.")

    # Log failed downloads
    if errors:
        error_log = args.logging_dir / "failed_literaryqa_downloads.tsv"
        with error_log.open("w", encoding="utf-8") as f:
            writer = DictWriter(f, fieldnames=["doc_id", "book_id", "split", "url"], delimiter="\t")
            writer.writeheader()
            for err in errors:
                writer.writerow(err)
        logger.info(f"Logged failed downloads to {error_log}")

    ### Cleaning step ###
    for split, samples in literaryqa_urls.items():
        logger.info(f"Cleaning downloaded books for split: {split}")

        missing = []
        processed = set()
        for _, book_id, _ in (pbar := tqdm(samples, desc=f"Cleaning books for {split}")):
            input_html_path = args.output_dir / split / f"{book_id}.htm"
            output_txt_path = args.output_dir / split / f"{book_id}.cleaned.txt"
            log_file_path = args.logging_dir / split / f"{book_id}_cleaning.log"

            pbar.set_description(f"> {input_html_path.name}")
            html = detect_encoding_and_read(input_html_path)
            if html is None:
                missing.append(book_id)
                continue

            clean_and_save(
                gt_id=book_id,
                raw_text=extract_raw_text(html),
                normalize=True,
                output_file=output_txt_path,
                log_file=log_file_path,
            )

            processed.add(book_id)

        logger.info(f"Completed cleaning for split: {split}. Processed {len(processed)} books.")
        if missing:
            logger.warning(f"{len(missing)} missing or unreadable books:")
        for book_id in missing:
            logger.warning(f"- {book_id}")

    logger.info("Download and cleaning process completed.")

    if not args.write_as_jsonl:
        return

    ### Optional: Write the complete dataset as JSONL files
    output_folder = args.output_dir / "jsonl"
    output_folder.mkdir(parents=True, exist_ok=True)
    logger.info("Writing complete dataset as JSONL files...")

    splitpaths = ANNOTATIONS_FOLDER.glob("*.jsonl")
    for splitpath in splitpaths:
        split = splitpath.stem
        split_data = [json.loads(line) for line in splitpath.open("r", encoding="utf-8").readlines()]

        with (output_folder / f"{split}.jsonl").open("w+", encoding="utf-8") as f_out:
            for item in tqdm(split_data, desc=f"Writing {split} JSONL"):
                book_id = item["gutenberg_id"]
                cleaned_path = args.output_dir / split / f"{book_id}.cleaned.txt"
                if cleaned_path.exists():
                    item["text"] = cleaned_path.read_text(encoding="utf-8")
                else:
                    item["text"] = None
                f_out.write(json.dumps(item) + "\n")
    logger.info(f"Completed writing JSONL files to {output_folder}")


if __name__ == "__main__":
    args = ScriptArgs().parse_args()
    main(args)

"""Clean Project Gutenberg HTML for NarrativeQA by extracting readable text.

This module cleans HTML exported from Project Gutenberg to produce normalized
plain text for QA tasks. It removes boilerplate (headers/footers, license
sections), handles special structures (poems, stage directions, sidebars), and
collects diagnostics about residual Gutenberg markers.
"""

# ===== Imports ===== #
import re
import os
import json
import pandas as pd
from tap import Tap
from tqdm import tqdm
from pathlib import Path
from datasets import load_dataset
from src.logging_utils import log, loguru_setup
from src.download_narrativeqa_html import detect_encoding_and_read
from bs4 import BeautifulSoup, NavigableString, XMLParsedAsHTMLWarning

import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ===== Cleaning rules and markers ===== #

START_MARKERS = [
    "***START OF THIS PROJECT GUTENBERG EBOOK",
    "*** START OF THIS PROJECT GUTENBERG EBOOK",
    "***START OF THE PROJECT GUTENBERG EBOOK",
    "*** START OF THE PROJECT GUTENBERG EBOOK",
    # specific markers for some books
    "while Coxeter and Mason write Novall alone in , and Novall Senior thereafter. I have not thought it worth while to note the variants of the several texts on this point.",  # 44015
]
END_MARKERS = [
    "End of the Project Gutenberg",
    "END OF THIS PROJECT GUTENBERG",
    "End of Project Gutenberg",
    "*** START: FULL LICENSE",
    "THE FULL PROJECT GUTENBERG LICENSE",
    # "this etext was produced from",  # 5013 --> this breaks the text
    # "this e-text was produced from", # this patterns is found also at the start of the html
    "NOW you can get ADVANCE COPIES of the best",  # 50571
    "AN ALPHABETICAL LIST OF BOOKS CONTAINED IN BOHN'S LIBRARIES",  # 50966
    "Brilliant New Novel from Award-Winning Author of",  # 20121
]
STRICT_END_MARKERS = [  # these must match exactly
    r"^addendum[\.:;]?$",
    r"^books on nature study by$",
    r"^advertisements?[\.:;]?$",
    r"^appendix",
    r"^index[\.:;]?$",
]

# use with re.IGNORECASE and re.MULTILINE
# DO NOT USE re.DOTALL!
GUTENBERG_PRODUCTION_PATTERNS = [
    # DO NOT CHANGE THE ORDER
    r"^produced by[\w\W\s]*online[\n ]*distributed[\n ]*proofreading[\n ]*team.*(\nfile was produced from images.*\nby.*\))?($\n?^.*https?://\S+.*$)?",
    # these are the names of the most frequent contributors)
    r"^produced by.*(David Widger|Greg Weeks|Melissa Er-Raqabi|the PG Online|John Bickers|Dagny|Robert Cicconetti|David Garcia|Al Haines|Judith Boss|An Anonymous Volunteer|Distributed|Martin Pettit|Judy Boss|Nick Hodson of London|England|Eve Sobol|Les Bowler|John Hamm|David Reed|Martin Adamson\.|Malcolm Farmer|).*",
    r"^text file produced by.*(\nproofreaders team.*)?",
    r"^html file produced by david widger",
]

GUTENBERG_PREFACE_PATTERNS = [
    r"^The Project Gutenberg eBook of\s*.*$",
    r"^Title:\s*.*",
    r"^Author:\s*.*$",
    r"^Illustrator:\s*.*$",
    r"^Translator:\s*.*$",
    r"^Editor:\s*.*$",
    r"^Release Date:\s*.*$",
    r"^Language:\s*.*$",
    r"^Credits:\s*.*$",
    r"^Original publication:\s*.*$",
    r"^Character set encoding:\s*.*$",
]

SKIP_LINE_MARKERS = [
    r"\be-text\b",
    r"\betext\b",
    r"\be-book\b",
    r"\bebook\b",
    r"^(table of )?contents?[\.:;]?$",
    r"hyphenation",
    r"typographical errors?",
    r"^list of illustrations$",
    r"^illustrations$",
    r"^footnotes?[\.:;]?$",
    r"^linenotes?[\.:;]?$",
    r"^[\*\t ]*$",
    r"^§ \d*$",
    r"\binternet archive\b",
    r"\bemail\b",
    r"\be-mail\b",
    r"http:\/\/www",
    r"book was produced from scanned images of public domain",
    r"\bGoogle\b",
    r"Inconsistencies in the author's use of hyphens and accent marks",
    r"\bcontent providers?\b",
]

SECOND_SKIP_LINE_MARKERS = [
    r"©",
    r"Printed in U\.\s+S\.\s+A\.",
    r"^All Rights Reserved$",
    r"\btable of contents with hyperlinks\b",
]

OTHER_MARKERS = [
    "www.gutenberg.org",
    "etext",
    " e-text",
    "ebook",
    " e-book",
    "gutenberg",
    "projectgutenberg",
    "project-gutenberg",
]


# ===== Aggregation structures (failures report) ===== #
failures_df = {
    "file": [],
    "nqa_error": [],
    "tr_error": [],
    "nqa_start_markers_pos": [],
    "nqa_end_markers_pos": [],
    "nqa_other_markers_pos": [],
    "tr_start_markers_pos": [],
    "tr_end_markers_pos": [],
    "tr_other_markers_pos": [],
}


class ScriptArgs(Tap):
    """Command-line arguments for the HTML cleaning script.

    Attributes:
        id: Optional Gutenberg numeric ID to restrict processing to a single book.
        limit: Max number of items to process per split (-1 means no limit).
        input: Directory containing input HTML files (per split).
        output: Directory where cleaned text and reports will be written.
        normalize: If True, normalize punctuation to ease comparison with NQA text.
    """

    id: str | None = None  # to process a single book by its Gutenberg ID
    limit: int = -1  # max number of items to process per split (-1 means no limit)
    input: str = "data/narrativeqa"
    output: str = "data/narrativeqa_clean"
    splits: str = (
        "test"  # dash-separated list of splits to process, e.g. "train-validation-test"
    )
    normalize: bool = False  # normalizes punkt for easy comparison, can be disabled
    nqa_hf_path: str = "deepmind/narrativeqa"

    def process_args(self):
        """Normalize paths, ensure output dir exists, and initialize logging."""
        self.input_path = Path(self.input)
        self.output_path = Path(self.output)
        self.data_splits = self.splits.split("-")
        for split in self.data_splits:
            os.makedirs(self.output_path / split, exist_ok=True)
        loguru_setup()


def get_hash2id_map(
    input_file: str = "data/narrativeqa_clean/narrativeqa_id_hash_map.tsv",
):
    """Load map from NarrativeQA document IDs (hashes) to Gutenberg IDs.

    Args:
        input_file: Path to a TSV with columns `id` and `book_id`.

    Returns:
        A dict mapping NarrativeQA `id` to Gutenberg `book_id`.
    """
    id_map = {}
    df = pd.read_csv(input_file, sep="\t")
    for _, row in df.iterrows():
        id_map[row["id"]] = row["book_id"]
    return id_map


def _keep_alt_img_text(soup: BeautifulSoup):
    """Replace images with their title/alt text and merge adjacent content.

    Args:
        soup: A BeautifulSoup document to be modified in place.
    """
    # Find all image tags
    for img in soup.find_all("img"):
        alt_text = img.get("title", "").strip()
        if not alt_text:
            alt_text = img.get("alt", "").strip()

        # Get the parent element
        parent = img.parent

        # Find the position of the img tag in its parent's contents
        img_index = parent.contents.index(img)

        # Replace the img tag with its alt text
        img.replace_with(NavigableString(alt_text))

        # If there's content after the image and it's a string,
        # and the previous content (now the alt text) is also a string,
        # then merge them
        if (
            img_index + 1 < len(parent.contents)
            and isinstance(parent.contents[img_index], NavigableString)
            and isinstance(parent.contents[img_index + 1], NavigableString)
        ):

            # Get the content
            content_after = parent.contents[img_index + 1].string

            # Create a new string with merged content
            new_text = NavigableString(
                parent.contents[img_index].string + content_after
            )

            # Replace both nodes with the merged content
            parent.contents[img_index].replace_with(new_text)
            parent.contents[img_index + 1].extract()


def _remove_sidebar(soup: BeautifulSoup):
    """Flatten common sidebar structures by unwrapping span/div containers.

    Args:
        soup: A BeautifulSoup document to be modified in place.
    """
    # Find all divs with class 'sidebar'
    for sidebar_div in soup.find_all("div", class_="sidebar"):
        # Inside each sidebar, find all <p> tags
        for p_tag in sidebar_div.find_all("p"):
            # Inside each <p>, find all <span> tags and unwrap them
            for span in p_tag.find_all("span"):
                span.unwrap()
        # After fixing spans, unwrap the sidebar div itself (keep its content)
        sidebar_div.unwrap()


def _keep_songs(soup: BeautifulSoup):
    """Normalize song structures into <pre> blocks with line breaks.

    Args:
        soup: A BeautifulSoup document to be modified in place.
    """
    for songs_div in soup.find_all("div", id="songs"):
        for song_div in songs_div.find_all("div", class_="song"):

            lines = [
                line.get_text(strip=True)
                for line in song_div.find_all("div", class_="line")
            ]
            song_text = "\n\n".join(lines)

            # Create a new <pre> tag and insert the song text
            pre_tag = soup.new_tag("pre")
            pre_tag.append(NavigableString(song_text))

            # Replace the original <div class="song"> with the new <pre>
            song_div.replace_with(pre_tag)
        songs_div.unwrap()


def _keep_span_margin_left(soup: BeautifulSoup):
    """Promote <span style="margin-left: Xem;"> to block-level <p> tags.

    Args:
        soup: A BeautifulSoup document to be modified in place.
    """
    for span in soup.find_all("span"):
        style = span.get("style", "")
        if re.search(r"margin-left:\s*[\d.]+em;", style):
            span.name = "p"
            del span["style"]


def extract_raw_text(html_content, **kwargs):
    """Extract readable raw text from Gutenberg HTML content.

    Applies a series of BeautifulSoup-based transformations to remove
    boilerplate and normalize content such as poems, drop-caps, sidebars,
    page numbers, links, and footnotes. See implementation for supported
    keyword options.

    Args:
        html_content: The raw HTML string to be cleaned.
        **kwargs: Optional feature flags to customize cleaning behavior.

    Returns:
        A cleaned, human-readable text string.
    """
    # ugly page numbers in 31422
    # ugly referencens in 804
    table = {
        '<div class="stage-direction center">': '<div class="stage-direction">',
        # '<span style="margin-left: 2.5em;">': "<p>",
        # '<span style="margin-left: 3em;">': "<p>",
        # '<span style="margin-left: 18em;">': "<p>",
    }
    html_content = html_content.translate(table)
    soup = BeautifulSoup(html_content, "html5lib")

    if kwargs.get("keep_alt_img_text", True):
        _keep_alt_img_text(soup)

    if kwargs.get("remove_img", True):
        for class_name in ["tnote", "transnote", "covernote"]:
            for div in soup.find_all("div", class_=class_name):
                div.decompose()

    if kwargs.get("remove_tn", True):
        for class_name in ["footnote", "footnotes"]:
            for div in soup.find_all("div", class_=class_name):
                div.decompose()

    # Remove page number spans
    if kwargs.get("remove_pagenum", True):
        for class_name in ["pagenum", "ns", "pageno"]:
            for span in soup.find_all("span", class_=class_name):
                span.decompose()  # completely remove the tag and its content

    # Remove citation links (e.g., <a href="#footnote557">[557]</a>)
    if kwargs.get("remove_citation", True):
        for a_tag in soup.find_all("a", class_="citation"):
            a_tag.decompose()  # remove the citation link

    # Remove all <a> tags completely, including their content
    if kwargs.get("remove_links", True):
        for a_tag in soup.find_all("a", href=True):
            a_tag.decompose()

    if kwargs.get("remove_sidebar", True):
        _remove_sidebar(soup)

    if kwargs.get("keep_dropcap", True):
        for div in soup.find_all("div", class_="drop-cap"):
            div.name = "p"
        for tag in soup.find_all("div", class_="center"):
            tag.unwrap()

    if kwargs.get("keep_span_margin_left", True):
        _keep_span_margin_left(soup)

    if kwargs.get("keep_poem", True):
        for poem_div in soup.find_all("div", class_="poem"):
            # Handle stanza-based poems (with <div class="stanza">)
            for stanza_div in poem_div.find_all("div", class_="stanza"):
                for span in stanza_div.find_all("span"):
                    span.unwrap()
                for br in stanza_div.find_all("br"):
                    br.replace_with("\n")
                stanza_div.unwrap()

            # Handle paragraph-based poems (<p> lines)
            for p in poem_div.find_all("p"):
                # Insert newline after each <p>
                p.insert_after(soup.new_tag("br"))
                p.unwrap()

            poem_div.name = "pre"
            del poem_div["class"]

    # e.g., in 44015 in the test set
    if kwargs.get("keep_stage_dir", True):
        for div in soup.find_all("div", class_="stage-direction"):
            div.name = "p"

    # e.g., in 44015 in the test set
    if kwargs.get("keep_scene_desc", True):
        for div in soup.find_all("div", class_="scene-description"):
            div.name = "p"

    # e.g., in 44015 in the test set
    if kwargs.get("keep_songs", True):
        _keep_songs(soup)

    # e.g., tags found in 44015 in the test set
    for div_id in ["notes", "footnotes", "linenotes"]:
        for tag in soup.find_all("div", id=div_id):
            tag.decompose()

    for p in soup.find_all("p", class_="hang"):
        p.decompose()

    allowed_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "pre"}
    output_lines = []

    for tag in soup.find_all(allowed_tags):

        if tag.name == "pre":
            # preserve \n inserted from <br>
            text = tag.get_text(separator="\n", strip=True)
        else:
            text = tag.get_text(separator=" ", strip=True)

        # Remove leftover inline [Pg 123], [Page 45], etc.
        if kwargs.get("remove_pagenum", True):
            text = re.sub(r"\[(Pg|Page)\s*\d+\]", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"\[p\s*\d+\s*\]", " ", text, flags=re.IGNORECASE)
            text = re.sub(
                r"^p\.\s+\d+:.*$",
                " ",
                text,
                flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
            )

        # Remove citation placeholders like [557], [1], etc.
        if kwargs.get("remove_citation", True):
            text = re.sub(r"\[\d+\]", " ", text)

        if kwargs.get("remove_footnotes", True):
            text = re.sub(r"\[[ivxlcm]+\]", " ", text)  # only lowecase!

        if kwargs.get("remove_transnotes", True):
            # Remove transcriber notes like [transcriber's note: ...]
            text = re.sub(
                r"\[transcriber.*s note.*\]",
                " ",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            text = re.sub(
                r"^transcriber.*s note[s]?:?",
                " ",
                text,
                flags=re.IGNORECASE | re.MULTILINE,
            )

        # Normalize whitespace
        if kwargs.get("normalize_whitespace", True):
            # removes possible extra spaces before punctuation
            text = re.sub(r"\s+([?!.,:;])", r"\1", text)
            text = re.sub(r"\(\s+", "(", text)
            text = re.sub(r"\s+\)", ")", text)
            text = text.replace(" ( ) ", "")
            # Keep newlines for <pre> tags
            if tag.name != "pre":
                text = text.replace("\n", " ")
                text = " ".join(text.split())

        # Avoid empty lines and junks
        if not text or (  # or len(text) < 2:
            kwargs.get("remove_pagenum", True)
            and re.search(
                r"^p. \d+:", text, flags=re.IGNORECASE | re.DOTALL | re.MULTILINE
            )
        ):
            continue

        # Remove other gutenberg info
        if kwargs.get("remove_gutenberg_preface", True):
            for pattern in GUTENBERG_PRODUCTION_PATTERNS:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
            # for pattern in GUTENBERG_PREFACE_PATTERNS:
            #     text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

        output_lines.append(text)

    return "\n\n".join(output_lines)


def remove_gutenberg_info(
    raw_text: str | list[str], gt_id: int, log_file: Path | None = None
):
    """Remove Gutenberg boilerplate from raw text and track markers.

    Scans the provided text for start/end markers, removes lines matching skip
    patterns, and returns a cleaned text along with the positions of detected
    start/end markers.

    Args:
        raw_text: The input text either as a single string or a list of lines.
        gt_id: Gutenberg book ID (used for logging context only).
        log_file: Optional path to a log file where matched markers/lines are recorded.

    Returns:
        A tuple ``(clean_text, start_markers_pos, end_markers_pos)``.
    """
    if type(raw_text) is str:
        splitted = raw_text.split("\n")
    else:
        splitted = raw_text
    num_lines = len(splitted)

    text = []
    s_markers_pos = []
    e_markers_pos = []

    if log_file:
        log_out = open(log_file, "w")
        log_out.write("Line_id\tMarker\tLine\t\n")
    for i, line in enumerate(raw_text.split("\n")):
        line = line.strip()
        if not line:
            continue

        # Skip lines that contain any of the skip markers
        skip_flag = False
        for marker in SKIP_LINE_MARKERS:
            if re.search(marker, line, flags=re.IGNORECASE | re.MULTILINE):
                skip_flag = True
                if log_file:
                    log_out.write(f"{i}\t{marker}\t{json.dumps(line)}\n")
                break
        if skip_flag:
            continue

        s_flag = False
        e_flag = False

        # Check if the line contains any of the start markers
        for marker in START_MARKERS:
            if marker.lower() in line.lower():
                text = []
                s_flag = True
                s_markers_pos.append(i)
                if log_file:
                    log_out.write(f"{i}\t{marker}\t{json.dumps(line)}\n")
                break
        if s_flag:
            continue

        for pattern in GUTENBERG_PREFACE_PATTERNS:
            if re.match(pattern, line, flags=re.IGNORECASE | re.MULTILINE):
                text = []
                s_flag = True
                s_markers_pos.append(i)
                if log_file:
                    log_out.write(f"{i}\t{pattern}\t{json.dumps(line)}\n")
                break
        if s_flag:
            continue

        # Check if the line contains any of the end markers
        end_marker = None
        for marker in END_MARKERS:
            if marker.lower() in line.lower():
                e_flag = True
                end_marker = marker
                e_markers_pos.append(i)
                if log_file:
                    log_out.write(f"{i}\t{marker}\t{json.dumps(line)}\n")
                break

        if not e_flag:
            for marker in STRICT_END_MARKERS:
                if re.search(marker, line, flags=re.IGNORECASE | re.MULTILINE):
                    e_flag = True
                    end_marker = marker
                    e_markers_pos.append(i)
                    if log_file:
                        log_out.write(f"{i}\t{marker}\t{json.dumps(line)}\n")
                    break

        if e_flag:
            # if the marker is in the clear marker list, truncate safely
            if end_marker in END_MARKERS:
                break
            else:
                p = i / num_lines
                # ignore the end marker if it is found in the first half of the text
                if p < 0.5:
                    if log_file:  # also used to enable console prints
                        log.info(
                            f"[{gt_id}] >> Found end marker `{end_marker}` in line {i}/{num_lines} ({100*p:.2f}) --> ignored"
                        )
                # if the end marker is found in the second half of the text, log it and truncate
                elif 0.5 <= p < 0.85:
                    if log_file:
                        log.info(
                            f"[{gt_id}] >> Found end marker `{end_marker}` in line {i}/{num_lines} ({100*p:.2f}) --> check"
                        )
                    # print(line)
                    break
                # if the end marker is found in the last 15% of the text, truncate safely
                else:
                    break

        # Skip lines that contain any of the second skip markers
        # do not change the order of these operations!!
        skip_flag = False
        for marker in SECOND_SKIP_LINE_MARKERS:
            if re.search(marker, line, flags=re.IGNORECASE | re.MULTILINE):
                skip_flag = True
                if log_file:
                    log_out.write(f"{i}\t{marker}\t{json.dumps(line)}\n")
                break
        if skip_flag:
            continue
        text.append(line)
    if log_file:
        log_out.close()

    return "\n".join(text)


def clean_and_save(
    gt_id: int,
    raw_text: str,
    normalize: bool = False,
    output_file: str | None = None,
    log_file: str | None = None,
):
    """Clean text using Gutenberg rules and optionally save to disk.

    Args:
        gt_id: Gutenberg book ID used for context/logging.
        raw_text: The source text to clean (NQA text or extracted HTML text).
        output_file: Optional path where the cleaned text will be written.
        log_file: Optional path to a log file of matched markers/lines.
    """
    # additional cleaning
    text = remove_gutenberg_info(raw_text=raw_text, gt_id=gt_id, log_file=log_file)
    if normalize:
        text = (
            text.replace("--", "—")
            .replace("——", "—")
            .translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
        )

    # save cleaned versions
    if output_file:
        os.makedirs(output_file.parent, exist_ok=True)
        with open(str(output_file), "w") as out_file:
            out_file.write(text)


def main(args: ScriptArgs, nqa_split, split: str, id_map: dict):
    """Process one split: clean texts and write reports.

    Iterates over NarrativeQA samples, cleans both the original NQA text and
    the text extracted from HTML, writes outputs and logs, and updates a CSV
    summarizing problematic cases.

    Args:
        args: Parsed CLI arguments.
        split: Dataset split name (e.g., "train", "validation", "test").
        id_map: Mapping from NarrativeQA hashes to Gutenberg IDs.
    """
    missing = []
    processed = set()
    for i, row in (
        pbar := tqdm(enumerate(nqa_split), total=len(nqa_split), disable=False)
    ):
        gt_id = id_map[row["document"]["id"]]
        if args.id and str(gt_id) != str(args.id):
            continue

        if i == args.limit:
            break

        if gt_id in processed:
            continue

        input_file = args.input_path / split / f"{gt_id}.htm"

        # Clean the html file
        pbar.set_description(f"> {input_file}")
        html = detect_encoding_and_read(input_file)
        if not html:
            missing.append(input_file)
            continue

        clean_and_save(
            gt_id=gt_id,
            raw_text=extract_raw_text(html),
            normalize=args.normalize,
            output_file=args.output_path / split / f"{gt_id}.cleaned.txt",
            log_file=args.output_path / split / f"{gt_id}_cleaning.log",
        )

        processed.add(gt_id)

    log.info(f"> Missing files: {len(missing)}")
    for file in missing:
        log.info(f"- {file}")


if __name__ == "__main__":
    args = ScriptArgs().parse_args()

    id_map = get_hash2id_map()  # map from nqa_hash to gutenberg book_id

    # nqa = load_dataset("sapienzanlp/narrativeqa")
    log.info(f"Loading NarrativeQA dataset from {args.nqa_hf_path}")
    nqa = load_dataset(args.nqa_hf_path)
    for split in args.data_splits:
        nqa_split = nqa[split].filter(lambda x: x["document"]["kind"] == "gutenberg")
        main(args, nqa_split=nqa_split, split=split, id_map=id_map)

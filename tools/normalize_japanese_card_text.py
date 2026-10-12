"""Reflow source Japanese text and install explicitly verified face transcriptions.

This tool never reconstructs missing rules. Unresolved OCR findings are printed
with their card IDs; their content remains available for source-image review.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIED = ROOT / "data/card_ability_face_verified.tsv"
SOURCE = ROOT / "data/cards_bilingual_v4.tsv"
PC02R = ROOT / "zz/pc02r_data.tsv"
RARITIES = {"COMMON", "RARE", "EPIC", "LEGEND", "BASIC"}
OCR_WORDS = {"ミ二オン": "ミニオン", "タ一ン": "ターン", "たぴ": "たび"}


def read_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    if not fields or "image_id" not in fields:
        raise ValueError(f"missing image_id header: {path}")
    ids = [row["image_id"] for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"missing/duplicate card IDs: {path}")
    return fields, rows


def write_rows(path: Path, fields, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")


def normalize_text(value: str) -> str:
    """Remove card-face wrapping while retaining timing/scope paragraphs.

    Recognized headings stay on their own lines. Headings inside a quoted
    granted ability stay in that sentence, including across source OCR wraps.
    No missing punctuation or missing sentence is supplied here.
    """
    lines = value.replace("\\n", "\n").replace("\r", "").split("\n")
    kept = []
    for line in lines:
        line = line.strip()
        rarity = unicodedata.normalize("NFKC", line).upper().replace("Ⅰ", "I")
        if rarity in RARITIES:
            continue
        if line:
            kept.append(line)
    paragraphs = []
    quote_depth = 0
    previous_heading = False
    for line in kept:
        keyword = bool(re.fullmatch(r"襲撃|奪命|再起|貫通|潜入|飛来|連携[：・].+|加護[：・].+|コスト軽減：.+", line))
        enumeration = bool(re.fullmatch(r"(?:「[^」]+」\s*){2,}", line))
        new_paragraph = quote_depth == 0 and (line.startswith(("【", "《", "進化：")) or keyword or enumeration or previous_heading)
        if paragraphs and new_paragraph:
            paragraphs.append("\n")
        paragraphs.append(line)
        quote_depth += line.count("「") - line.count("」")
        previous_heading = keyword or line.startswith("進化：") or bool(re.fullmatch(r"《[^》]+》", line))
    text = "".join(paragraphs)
    # These three are character-shape OCR substitutions, never rule inference.
    for wrong, correct in OCR_WORDS.items():
        text = text.replace(wrong, correct)
    # Only paragraph-leading headings are split from their body. A timing
    # reference embedded in a sentence is deliberately left in that sentence.
    text = re.sub(r"(?m)^(《[^》]+》)(?=.)", r"\1\n", text)
    text = re.sub(r"(?m)^(【[^】\n]+】(?:\s*[/／&＆]\s*【[^】\n]+】)*)(?=.)", r"\1\n", text)
    return text.strip().replace("\n\n", "\n").replace("\n", "\\n")


def integrity_findings(value: str) -> list[str]:
    text = value.replace("\\n", "\n")
    findings = []
    for opening, closing in (("【", "】"), ("「", "」"), ("《", "》"), ("[", "]"), ("［", "］"), ("『", "』"), ("«", "»")):
        if text.count(opening) != text.count(closing):
            findings.append(f"unbalanced {opening}{closing}")
    if text.count("(") + text.count("（") != text.count(")") + text.count("）"):
        findings.append("unbalanced parentheses")
    keyword_tail = re.search(r"(?:［|\[)?(?:襲撃|奪命|再起|貫通|潜入|飛来|連携[：・][^\n]+|加護[：・:][^\n]+)(?:］|\])?$", text)
    evolution_tail = re.search(r"進化：[^\n]+(?:とき|とする)$", text)
    enumeration_tail = re.search(r"[。\n](?:「[^」]+」\s*){2,}$", text)
    if text and not re.search(r"[。)）]$|^効果なし$", text) and not keyword_tail and not evolution_tail and not enumeration_tail:
        findings.append("unfinished sentence or unknown keyword")
    if re.search(r"【[^】\n]*夕|召唤|配置时|加蔬|加時】|付与能カ|付与能》|力ー|力一|力ド|フ才|ミ二|ミ三|三二|三ニ|ニ才|�|メインノ|メイン」|】ノ|フラッシュ\)|タ-ン|夕一ン|\[加(?:は|を)|この二|このニ|フォス|ダメーを|フルド|フィルド|カド|カ一ド|カ-ド|ゲ一ム|ゲム", text):
        findings.append("OCR token")
    if re.search(r"^\[(?!加護|連携|襲撃|奪命|再起|貫通|潜入|飛来)[^\]]+\]", text):
        findings.append("card title/layout text")
    if re.search(r"(?:BP|DP)[+-]?[0-9]*[ＯOIl]|このター(?:中|の)|ダメジ|破壊さる|プレイヤ[^ー]", text):
        findings.append("OCR word/number fragment")
    return findings


def install(apply: bool = False) -> dict:
    fields, rows = read_rows(SOURCE)
    pc_fields, pc_rows = read_rows(PC02R)
    _, verified_rows = read_rows(VERIFIED)
    overrides = {r["image_id"]: r for r in verified_rows}
    pc_by_id = {r["image_id"]: r for r in pc_rows}
    changed, pc_changed, unresolved = [], [], []
    for row in rows:
        card_id = row["image_id"]
        verified = overrides.get(card_id)
        if verified:
            if verified["face_text_status"] not in {"text", "no_text"}:
                raise ValueError(f"invalid verification status: {card_id}")
            text = verified["ability_jp"]
            if (not text) != (verified["face_text_status"] == "no_text"):
                raise ValueError(f"verification content/status mismatch: {card_id}")
        else:
            text = row["ability_jp"]
        text = normalize_text(text)
        if row["ability_jp"] != text:
            row["ability_jp"] = text
            changed.append(card_id)
        if card_id in pc_by_id and pc_by_id[card_id]["ability_jp"] != text:
            pc_by_id[card_id]["ability_jp"] = text
            pc_changed.append(card_id)
        findings = integrity_findings(text)
        if findings:
            unresolved.append({"image_id": card_id, "name_jp": row["name_jp"], "findings": findings})
    if apply:
        write_rows(SOURCE, fields, rows)
        write_rows(PC02R, pc_fields, pc_rows)
    return {"scanned": len(rows), "pc02r_scanned": len(pc_rows), "changed": changed,
            "pc02r_changed": pc_changed, "unresolved": unresolved}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = install(args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["unresolved"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

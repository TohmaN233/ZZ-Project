"""Export plain, pack-separated Japanese text and safely import aligned Chinese text."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = Path("data/cards_bilingual_v4.tsv")
TARGET = Path("zz/web/translations/zz_card_pool_zh.tsv")


def read_tsv(path: Path, key: str):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    if not fields or key not in fields:
        raise ValueError(f"missing {key} column: {path}")
    ids = [row[key] for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"empty or duplicate {key}: {path}")
    return fields, rows


def write_tsv(path: Path, fields, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    temporary.replace(path)


def clean(value: str) -> str:
    return value.replace("\\n", "\n").strip()


def encode_line(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace("\t", "\\t")


def decode_line(text: str) -> str:
    output, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
            if index == len(text) or text[index] not in "nt\\":
                raise ValueError(f"invalid escape in translated line: {text!r}")
            char = {"n": "\n", "t": "\t", "\\": "\\"}[text[index]]
        output.append(char)
        index += 1
    return "".join(output).strip()


def source_signature(row):
    data = [row["image_id"], row.get("official_name_jp") or row["name_jp"], row["ability_jp"], row.get("pack_jp_official") or row["pack_jp"]]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def export_bundle(root: Path, output: Path):
    if output.exists():
        raise ValueError(f"output already exists; choose a new directory: {output}")
    _, source = read_tsv(root / SOURCE, "image_id")
    _, translated = read_tsv(root / TARGET, "card_id")
    current = {row["card_id"]: row for row in translated}
    verified_path = root / "data/card_ability_face_verified.tsv"
    verified = {}
    if verified_path.exists():
        _, rows = read_tsv(verified_path, "image_id")
        verified = {row["image_id"]: row for row in rows}
    packs = {}
    for row in source:
        old = current.get(row["image_id"], {})
        missing = [field for field in ("name_zh", "ability_zh") if not clean(old.get(field, ""))]
        if not missing:
            continue
        name = clean(row.get("official_name_jp") or row["name_jp"])
        ability = clean(row["ability_jp"])
        if not name:
            raise ValueError(f"missing Japanese name: {row['image_id']}")
        if not ability:
            if verified.get(row["image_id"], {}).get("face_text_status") != "no_text":
                raise ValueError(f"unverified empty Japanese effect: {row['image_id']}")
            ability = "効果なし"
        pack = row.get("pack_jp_official") or row["pack_jp"]
        if not pack:
            raise ValueError(f"missing card pack: {row['image_id']}")
        packs.setdefault(pack, []).append({
            "card_id": row["image_id"], "name_jp": name, "ability_jp": ability,
            "fields": missing, "previous": {field: old.get(field, "") for field in missing},
            "source_signature": source_signature(row),
        })
    # Validate all source data before creating any deliverables.
    (output / "source").mkdir(parents=True)
    (output / "translated").mkdir()
    manifest = {"version": 1, "packs": []}
    summary = []
    for index, (pack, cards) in enumerate(packs.items(), 1):
        slug = re.sub(r'[<>:"/\\|?*\s]+', "_", pack).strip("._")
        filename = f"{index:02d}_{slug}.txt"
        lines = [encode_line(card[field]) for card in cards for field in ("name_jp", "ability_jp")]
        (output / "source" / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
        manifest["packs"].append({"name": pack, "file": filename, "cards": cards})
        summary.append({"pack": pack, "file": filename, "cards": len(cards), "lines": len(lines)})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_tsv(output / "卡包清单.tsv", ["pack", "file", "cards", "lines"], summary)
    references = output / "references"
    references.mkdir()
    for filename in ("GLOSSARY.json", "zz_card_pool_zh.tsv", "zz_force_pool_zh.tsv"):
        shutil.copy2(root / "zz/web/translations" / filename, references / filename)
    by_id = {row["image_id"]: row for row in source}
    paired = [{"card_id": row["card_id"], "pack": by_id[row["card_id"]].get("pack_jp_official") or by_id[row["card_id"]]["pack_jp"],
               "name_jp": clean(by_id[row["card_id"]].get("official_name_jp") or by_id[row["card_id"]]["name_jp"]),
               "name_zh": row["name_zh"], "ability_jp": clean(by_id[row["card_id"]]["ability_jp"]), "ability_zh": row["ability_zh"]}
              for row in translated]
    write_tsv(references / "现有译名表.tsv", ["card_id", "pack", "name_jp", "name_zh"], [{key: row[key] for key in ("card_id", "pack", "name_jp", "name_zh")} for row in paired])
    write_tsv(references / "已有卡牌日中对照.tsv", ["card_id", "pack", "name_jp", "name_zh", "ability_jp", "ability_zh"], paired)
    from zz.web.filter_localization import FILTER_OPTION_LABELS, TIMING_LABELS
    terms = [{"group": group, "ja": ja, "zh": labels[0], "en": labels[1]}
             for group, values in FILTER_OPTION_LABELS.items() for ja, labels in values.items()]
    terms.extend({"group": "effect_timing", "ja": ja, "zh": labels[0], "en": labels[1]} for ja, labels in TIMING_LABELS.items())
    write_tsv(references / "界面分类与时点译名.tsv", ["group", "ja", "zh", "en"], terms)
    if (root / "docs/rules").exists():
        shutil.copytree(root / "docs/rules", references / "rules")
    shutil.copy2(Path(__file__), output / "card_translation_exchange.py")
    (output / "README.txt").write_text(
        "日文卡牌待译包 → 简体中文\n\n"
        "source 内每个 TXT 是一个卡包，只含待译文本：奇数行卡名，偶数行效果。\n"
        "效果中的 \\n 代表原来的换行；保留这些标记，不要拆成多行。\\t 是制表符，\\\\ 是字面反斜杠。\n"
        "请保持行数、卡牌顺序和文件名，不加编号、标题、空白分隔行或 Markdown 代码围栏。\n"
        "効果なし 对应已人工核实没有效果文本的卡，按术语表译为 无效果。\n"
        "译完放入 translated，可一次放一个或多个卡包；未提供的卡包不会导入。\n"
        "references/现有译名表.tsv 是现有卡名对应表；GLOSSARY.json 是效果术语基准。\n"
        "界面分类与时点译名另列参考：界面与效果正文用语存在差异，效果正文遵循 GLOSSARY 和现有译文。\n"
        "种族、卡包、类型、属性已有译文；当前数据未提供独立背景故事文本。\n\n"
        "从主仓库目录运行，先生成合并预览（不会改线上中文表）：\n"
        "python tools/card_translation_exchange.py import --bundle \"此待译包目录\" --translated \"此待译包目录/translated\" --output \"此待译包目录/zz_card_pool_zh.merged.tsv\"\n"
        "检查后回填实际中文表（显式写入）：\n"
        "python tools/card_translation_exchange.py import --bundle \"此待译包目录\" --translated \"此待译包目录/translated\" --output zz/web/translations/zz_card_pool_zh.tsv\n"
        "也可使用包内同名脚本，加 --project-root 主仓库路径。\n"
        "导入校验行数、非空、日文假名、源文本是否变化、已有中文是否冲突；全部通过后原子写入。\n"
        "已翻译字段不覆盖；映射见 manifest.json。导入后重启游戏以刷新翻译缓存。\n",
        encoding="utf-8",
    )
    return summary


def import_bundle(root: Path, bundle: Path, translated_dir: Path, output: Path, *, allow_effect_reflow: bool = False):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("unsupported translation manifest version")
    fields, rows = read_tsv(root / TARGET, "card_id")
    by_id = {row["card_id"]: row for row in rows}
    _, sources = read_tsv(root / SOURCE, "image_id")
    source_by_id = {row["image_id"]: row for row in sources}
    supplied = {path.name for path in translated_dir.glob("*.txt")}
    expected = {pack["file"] for pack in manifest["packs"]}
    if supplied - expected:
        raise ValueError(f"unknown translated filenames: {sorted(supplied - expected)}")
    if not supplied:
        raise ValueError("no translated TXT files supplied")
    imported = 0
    seen = set()
    for pack in manifest["packs"]:
        filename = pack["file"]
        if filename not in supplied:
            continue
        lines = (translated_dir / filename).read_text(encoding="utf-8-sig").splitlines()
        if len(lines) != len(pack["cards"]) * 2:
            raise ValueError(f"line count mismatch: {filename}: expected {len(pack['cards']) * 2}, got {len(lines)}")
        for index, card in enumerate(pack["cards"]):
            card_id = card["card_id"]
            if card_id in seen:
                raise ValueError(f"duplicate mapped card: {card_id}")
            seen.add(card_id)
            if card_id not in source_by_id or source_signature(source_by_id[card_id]) != card["source_signature"]:
                raise ValueError(f"Japanese source changed since export: {card_id}")
            if card_id not in by_id:
                new_row = {field: "" for field in fields}
                new_row["card_id"] = card_id
                rows.append(new_row)
                by_id[card_id] = new_row
            for offset, field in enumerate(("name_zh", "ability_zh")):
                if field not in card["fields"]:
                    continue
                text = decode_line(lines[index * 2 + offset])
                if not text or re.search(r"[ぁ-ゖァ-ヺ]", text):
                    raise ValueError(f"empty or untranslated Japanese: {filename}:{index * 2 + offset + 1}, {card_id}/{field}")
                old = by_id[card_id].get(field, "")
                if old != card["previous"][field] and clean(old) != text:
                    raise ValueError(f"Chinese translation conflict: {card_id}/{field}")
                if field == "ability_zh" and not allow_effect_reflow and text.count("\n") != card["ability_jp"].count("\n"):
                    raise ValueError(f"effect newline markers changed: {card_id}")
                by_id[card_id][field] = text
            imported += 1
    write_tsv(output, fields, rows)
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    importer = commands.add_parser("import")
    importer.add_argument("--bundle", type=Path, required=True)
    importer.add_argument("--translated", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    importer.add_argument("--allow-effect-reflow", action="store_true", help="Allow translated effects to rewrap internal lines; card count and source validation remain strict")
    args = parser.parse_args()
    try:
        if args.command == "export":
            summary = export_bundle(args.project_root, args.output)
            print(json.dumps({"cards": sum(row["cards"] for row in summary), "packs": summary}, ensure_ascii=False, indent=2))
        else:
            count = import_bundle(args.project_root, args.bundle, args.translated, args.output, allow_effect_reflow=args.allow_effect_reflow)
            print(f"Imported {count} cards into {args.output}")
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()

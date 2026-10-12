import json
import shutil

import pytest

from tools.card_translation_exchange import ROOT, SOURCE, TARGET, decode_line, encode_line, export_bundle, import_bundle, read_tsv, write_tsv


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("translation_project")
    source_rows = [
        {"image_id": "old", "name_jp": "既存カード", "ability_jp": "既存効果", "pack_jp": "PC:01"},
        {"image_id": "new", "name_jp": "新カード", "ability_jp": "第一行\\n第二行", "pack_jp": "PC:03"},
        {"image_id": "partial", "name_jp": "部分カード", "ability_jp": "既存効果", "pack_jp": "PC:04"},
        {"image_id": "vanilla", "name_jp": "通常カード", "ability_jp": "", "pack_jp": "PC:04"},
    ]
    write_tsv(root / SOURCE, ["image_id", "name_jp", "ability_jp", "pack_jp"], source_rows)
    write_tsv(root / TARGET, ["card_id", "name_zh", "ability_zh"], [
        {"card_id": "old", "name_zh": "已有卡", "ability_zh": "已有第一行\r\n已有第二行"},
        {"card_id": "partial", "name_zh": "", "ability_zh": "已有部分效果"},
    ])
    write_tsv(root / "data/card_ability_face_verified.tsv", ["image_id", "face_text_status"], [{"image_id": "vanilla", "face_text_status": "no_text"}])
    for filename in ("GLOSSARY.json", "zz_force_pool_zh.tsv"):
        shutil.copy2(ROOT / "zz/web/translations" / filename, root / "zz/web/translations" / filename)
    return root


@pytest.fixture(scope="module")
def bundle(tmp_path_factory, project):
    output = tmp_path_factory.mktemp("translation") / "bundle"
    summary = export_bundle(project, output)
    assert sum(row["cards"] for row in summary) == 3
    assert len(summary) == 2
    return output


def translated_files(bundle, output, all_packs=True):
    output.mkdir()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    packs = manifest["packs"] if all_packs else manifest["packs"][:1]
    for pack in packs:
        lines = []
        for card in pack["cards"]:
            lines.extend(["译名" + card["card_id"], encode_line("中文效果" + "\n中文效果" * card["ability_jp"].count("\n"))])
        (output / pack["file"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def test_escape_roundtrip():
    text = "第一行\n第二行\t符号\\n"
    assert decode_line(encode_line(text)) == text


def test_all_packs_roundtrip_preserves_existing_chinese(bundle, project, tmp_path):
    translated_files(bundle, tmp_path / "translated")
    output = tmp_path / "merged.tsv"
    assert import_bundle(project, bundle, tmp_path / "translated", output) == 3
    _, old = read_tsv(project / TARGET, "card_id")
    _, new = read_tsv(output, "card_id")
    assert len(new) == 4
    by_id = {row["card_id"]: row for row in new}
    assert all(by_id[row["card_id"]][field] == value for row in old for field, value in row.items() if value)
    root = tmp_path / "project"
    for relative in (SOURCE, TARGET):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project / SOURCE, root / SOURCE)
    shutil.copy2(output, root / TARGET)
    assert import_bundle(root, bundle, tmp_path / "translated", output) == 3


@pytest.mark.parametrize("failure", ["line_count", "japanese", "newline", "unknown_file"])
def test_invalid_input_never_overwrites_output(bundle, project, tmp_path, failure):
    manifest = translated_files(bundle, tmp_path / "translated", all_packs=False)
    path = tmp_path / "translated" / manifest["packs"][0]["file"]
    lines = path.read_text(encoding="utf-8").splitlines()
    if failure == "line_count":
        lines.pop()
    elif failure == "japanese":
        lines[0] = "未翻訳テキスト"
    elif failure == "newline":
        lines[1] = "中文效果"
    else:
        (path.parent / "unknown.txt").write_text("无关文本", encoding="utf-8")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = tmp_path / "merged.tsv"
    output.write_text("保留原文件", encoding="utf-8")
    with pytest.raises(ValueError):
        import_bundle(project, bundle, path.parent, output)
    assert output.read_text(encoding="utf-8") == "保留原文件"


@pytest.mark.parametrize("failure", ["source_changed", "chinese_conflict"])
def test_changed_source_or_chinese_is_rejected(bundle, project, tmp_path, failure):
    manifest = translated_files(bundle, tmp_path / "translated", all_packs=False)
    root = tmp_path / "project"
    for relative in (SOURCE, TARGET):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / relative, root / relative)
    card_id = manifest["packs"][0]["cards"][0]["card_id"]
    if failure == "source_changed":
        fields, rows = read_tsv(root / SOURCE, "image_id")
        next(row for row in rows if row["image_id"] == card_id)["ability_jp"] += "変更"
        write_tsv(root / SOURCE, fields, rows)
    else:
        fields, rows = read_tsv(root / TARGET, "card_id")
        rows.append({"card_id": card_id, "name_zh": "已人工翻译", "ability_zh": "已有译文"})
        write_tsv(root / TARGET, fields, rows)
    with pytest.raises(ValueError, match="source changed|translation conflict"):
        import_bundle(root, bundle, tmp_path / "translated", tmp_path / "merged.tsv")
    assert not (tmp_path / "merged.tsv").exists()


def test_explicit_effect_reflow_preserves_text_and_still_rejects_card_misalignment(bundle, project, tmp_path):
    manifest = translated_files(bundle, tmp_path / "translated", all_packs=False)
    path = tmp_path / "translated" / manifest["packs"][0]["file"]
    path.write_text("译名new\n中文效果合为一行\n", encoding="utf-8")
    output = tmp_path / "merged.tsv"
    with pytest.raises(ValueError, match="newline markers"):
        import_bundle(project, bundle, path.parent, output)
    assert import_bundle(project, bundle, path.parent, output, allow_effect_reflow=True) == 1
    _, rows = read_tsv(output, "card_id")
    assert next(row for row in rows if row["card_id"] == "new")["ability_zh"] == "中文效果合为一行"
    before = output.read_bytes()
    path.write_text("译名new\n中文效果\n多出来的一行\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line count"):
        import_bundle(project, bundle, path.parent, output, allow_effect_reflow=True)
    assert output.read_bytes() == before

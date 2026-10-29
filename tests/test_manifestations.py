"""Ghost files cannot leave .haunt/manifestations/."""

from haunted_terminal.manifestations import banish, sandbox_root, write_manifestation


def test_path_escape_stays_in_the_sandbox(tmp_path):
    outside = tmp_path / "haunt-escape-proof.txt"
    written = write_manifestation(tmp_path, "../haunt-escape-proof.txt", "boo")
    assert not outside.exists()
    assert written == tmp_path / ".haunt" / "manifestations" / "haunt-escape-proof.txt"
    assert written.read_text(encoding="utf-8") == "boo"
    assert written.resolve().is_relative_to(sandbox_root(tmp_path))


def test_dotdot_and_absolute_names_are_flattened(tmp_path):
    dotted = write_manifestation(tmp_path, "..", "x")
    assert dotted.name == "whisper.txt"
    assert dotted.parent == sandbox_root(tmp_path)

    absolute = write_manifestation(tmp_path, "/tmp/haunt-escape-proof.txt", "lamp")
    assert absolute.name == "haunt-escape-proof.txt"
    assert absolute.parent.name == "manifestations"
    assert not (tmp_path / "haunt-escape-proof.txt").exists()


def test_body_is_capped(tmp_path):
    written = write_manifestation(tmp_path, "long.txt", "n" * 5000)
    assert len(written.read_text(encoding="utf-8")) == 4000


def test_banish_removes_only_manifestations(tmp_path):
    keep = tmp_path / "keep.txt"
    keep.write_text("stay", encoding="utf-8")
    write_manifestation(tmp_path, "ofrenda.txt", "candle")
    ignore = tmp_path / ".haunt" / ".gitignore"
    assert ignore.read_text(encoding="utf-8") == "*\n"
    assert banish(tmp_path) == 1
    assert keep.read_text(encoding="utf-8") == "stay"
    assert list((tmp_path / ".haunt" / "manifestations").iterdir()) == []
    assert ignore.exists()

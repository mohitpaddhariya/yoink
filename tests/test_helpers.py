import json

from helpers import slug_for, write_transcript


def test_slug_replaces_slashes_and_dots():
    assert slug_for("/Users/m/yoink") == "-Users-m-yoink"
    assert slug_for("/a/b.c") == "-a-b-c"


def test_write_transcript_is_parseable_and_placed(projects_root):
    path = write_transcript(
        projects_root,
        "s1",
        "/Users/m/yoink",
        turns=[("user", "why failing"), ("assistant", "it is token refresh")],
        titles=[("ai", "auth debugging")],
    )
    assert path.parent.name == "-Users-m-yoink"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["cwd"] == "/Users/m/yoink"
    assert records[-1]["type"] == "ai-title"
    assert records[-1]["aiTitle"] == "auth debugging"

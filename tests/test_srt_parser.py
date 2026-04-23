from parsing.speaker_color import color_for_speaker
from parsing.srt_parser import extract_speaker, parse_srt, parse_timestamp_to_ms


def test_parse_timestamp_to_ms() -> None:
    assert parse_timestamp_to_ms("00:00:01,250") == 1250
    assert parse_timestamp_to_ms("00:02:00,000") == 120000


def test_extract_speaker() -> None:
    speaker, text = extract_speaker("[Speaker 1] Hello there")
    assert speaker == "Speaker 1"
    assert text == "Hello there"

    speaker2, text2 = extract_speaker("No explicit marker")
    assert speaker2 == "Unknown"
    assert text2 == "No explicit marker"


def test_parse_srt_basic() -> None:
    content = """1
00:00:00,000 --> 00:00:02,000
[Speaker 1] Hello

2
00:00:02,000 --> 00:00:04,500
Plain segment
"""
    segments = parse_srt(content)
    assert len(segments) == 2
    assert segments[0].speaker == "Speaker 1"
    assert segments[0].text == "Hello"
    assert segments[1].speaker == "Unknown"
    assert segments[1].end_ms == 4500


def test_speaker_color_is_deterministic() -> None:
    c1 = color_for_speaker("Speaker 1")
    c2 = color_for_speaker("Speaker 1")
    c3 = color_for_speaker("Speaker 2")
    assert c1 == c2
    assert c1.startswith("#")
    assert c3.startswith("#")


def test_parse_json_payload_inside_single_srt_block() -> None:
    content = """1
00:00:00,000 --> 00:00:10,000
[{"Start":0,"End":1.25,"Speaker":0,"Content":"Hej"},{"Start":1.25,"End":2.5,"Speaker":1,"Content":"Halloj"}]
"""
    segments = parse_srt(content)
    assert len(segments) == 2
    assert segments[0].speaker == "Speaker 0"
    assert segments[0].text == "Hej"
    assert segments[0].end_ms == 1250
    assert segments[1].speaker == "Speaker 1"


def test_json_payload_is_not_mistaken_for_speaker_tag() -> None:
    content = """1
00:00:00,000 --> 00:00:10,000
[{"Start":0,"End":1.0,"Content":"A"},{"Start":1.0,"End":2.0,"Speaker":2,"Content":"B"}]
"""
    segments = parse_srt(content)
    assert len(segments) == 2
    assert segments[0].speaker == "Unknown"
    assert segments[0].text == "A"
    assert segments[1].speaker == "Speaker 2"

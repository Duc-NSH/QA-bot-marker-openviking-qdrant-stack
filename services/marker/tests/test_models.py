from pydantic import ValidationError
import pytest
from marker_svc.models import PageChunk, ConvertRequest, ConvertResponse


def test_page_chunk_valid():
    c = PageChunk(text="hello", section_heading="Intro", page_number=1, content_type="text")
    assert c.text == "hello"
    assert c.page_number == 1


def test_page_chunk_invalid_content_type():
    with pytest.raises(ValidationError):
        PageChunk(text="x", section_heading=None, page_number=1, content_type="video")


def test_convert_request_requires_file_path():
    with pytest.raises(ValidationError):
        ConvertRequest()  # type: ignore[call-arg]


def test_convert_response_chunks_default_empty():
    r = ConvertResponse(chunks=[])
    assert r.chunks == []

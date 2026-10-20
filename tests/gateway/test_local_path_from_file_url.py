"""``local_path_from_file_url`` decodes both forms of outbound ``file://`` image URL."""

from urllib.parse import quote

import pytest

from gateway.platforms.helpers import local_path_from_file_url


@pytest.mark.parametrize("name", ["shot one.png", "shot #1?.png", "100% a%20b.png"])
def test_gateway_and_standard_file_urls_decode_to_the_same_path(tmp_path, name):
    image = tmp_path / name
    assert local_path_from_file_url(f"file://{quote(str(image))}") == str(image)
    assert local_path_from_file_url(image.as_uri()) == str(image)

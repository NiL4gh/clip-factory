import os
from shorts_generator import clipper

ASSET = os.path.join(os.path.dirname(__file__), "..", "shorts_generator", "assets", "BebasNeue-Regular.ttf")

def test_family_name_from_file_reads_real_internal_name():
    # the real internal family name of the shipped TTF is "Bebas Neue"
    assert clipper._family_name_from_file(ASSET) == "Bebas Neue"

def test_family_name_from_file_bad_path_falls_back():
    assert clipper._family_name_from_file("/no/such/font.ttf") == "Bebas Neue"

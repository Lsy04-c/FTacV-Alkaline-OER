from pathlib import Path

from oer_aem import cpp_bridge


def test_cpp_library_path_uses_classified_build_directory():
    path = Path(cpp_bridge.library_path())
    assert path.parent.as_posix().endswith("code/cpp/build")

import pytest

from ai_creator_agent.env.binaries import (
    extension_suffixes, find_extension_module, find_library, import_optional,
    load_library, platform_lib_names,
)
from ai_creator_agent.env.errors import BinaryResolutionError


@pytest.mark.parametrize("system,expected", [
    ("Linux", ["libfoo.so", "foo.so"]),
    ("Darwin", ["libfoo.dylib", "foo.dylib"]),
    ("Windows", ["foo.dll", "libfoo.dll"]),
])
def test_platform_names(system, expected):
    assert platform_lib_names("foo", system) == expected


@pytest.mark.parametrize("stem", ["", "a/b", "a\\b"])
def test_invalid_stem(stem):
    with pytest.raises(BinaryResolutionError):
        platform_lib_names(stem, "Linux")


def test_env_override_wins(tmp_path):
    lib = tmp_path / "custom.so"
    lib.write_text("x")
    assert find_library("foo", [], {"AI_CREATOR_LIB_FOO": str(lib)}, "Linux") == lib


def test_env_override_missing_file_raises(tmp_path):
    with pytest.raises(BinaryResolutionError):
        find_library("foo", [], {"AI_CREATOR_LIB_FOO": str(tmp_path / "gone.so")}, "Linux")


def test_search_dir_prefers_exact_over_versioned(tmp_path):
    (tmp_path / "libfoo.so").write_text("a")
    (tmp_path / "libfoo.so.1.2").write_text("b")
    assert find_library("foo", [tmp_path], {}, "Linux").name == "libfoo.so"


def test_search_dir_finds_versioned_only(tmp_path):
    (tmp_path / "libfoo.so.1.2").write_text("b")
    assert find_library("foo", [tmp_path], {}, "Linux").name == "libfoo.so.1.2"


def test_not_found_returns_none(tmp_path):
    assert find_library("zz_not_a_real_lib_xyz", [tmp_path], {}, "Linux") is None


def test_load_library_uses_loader(tmp_path):
    (tmp_path / "libfoo.so").write_text("a")
    loaded = load_library("foo", [tmp_path], {}, "Linux", loader=lambda p: ("H", p))
    assert loaded.handle[0] == "H" and loaded.path.name == "libfoo.so"


def test_load_library_wraps_oserror(tmp_path):
    (tmp_path / "libfoo.so").write_text("a")
    def boom(_path):
        raise OSError("bad ELF header")
    with pytest.raises(BinaryResolutionError, match="bad ELF"):
        load_library("foo", [tmp_path], {}, "Linux", loader=boom)


def test_load_library_missing():
    with pytest.raises(BinaryResolutionError, match="not found"):
        load_library("zz_not_a_real_lib_xyz", [], {}, "Linux")


def test_extension_suffixes_longest_first():
    suffixes = extension_suffixes()
    assert suffixes == sorted(suffixes, key=len, reverse=True) and suffixes


def test_find_extension_module(tmp_path):
    target = tmp_path / ("fastmod" + extension_suffixes()[0])
    target.write_text("x")
    assert find_extension_module("fastmod", [tmp_path]) == target
    assert find_extension_module("other", [tmp_path]) is None


def test_extension_invalid_name(tmp_path):
    with pytest.raises(BinaryResolutionError):
        find_extension_module("../evil", [tmp_path])


def test_import_optional_primary():
    module, reason = import_optional("json")
    assert module is not None and reason is None


def test_import_optional_fallback():
    module, reason = import_optional("zz_missing_mod", "json")
    assert module.__name__ == "json" and reason is None


def test_import_optional_all_fail_reports_reasons():
    module, reason = import_optional("zz_missing_a", "zz_missing_b")
    assert module is None and "zz_missing_a" in reason and "zz_missing_b" in reason

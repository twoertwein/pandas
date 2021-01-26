"""
This module provides decorator functions which can be applied to test objects
in order to skip those objects when certain conditions occur. A sample use case
is to detect if the platform is missing ``matplotlib``. If so, any test objects
which require ``matplotlib`` and decorated with ``@td.skip_if_no_mpl`` will be
skipped by ``pytest`` during the execution of the test suite.

To illustrate, after importing this module:

import pandas.util._test_decorators as td

The decorators can be applied to classes:

@td.skip_if_some_reason
class Foo:
    ...

Or individual functions:

@td.skip_if_some_reason
def test_foo():
    ...

For more information, refer to the ``pytest`` documentation on ``skipif``.
"""
from contextlib import ContextDecorator
from distutils.version import LooseVersion
import locale
from typing import Optional
import warnings

import numpy as np
import pytest

from pandas.compat import IS64, is_platform_windows
from pandas.compat._optional import import_optional_dependency

from pandas.core.computation.expressions import NUMEXPR_INSTALLED, USE_NUMEXPR


def safe_import(mod_name: str, min_version: Optional[str] = None):
    """
    Parameters
    ----------
    mod_name : str
        Name of the module to be imported
    min_version : str, default None
        Minimum required version of the specified mod_name

    Returns
    -------
    object
        The imported module if successful, or False
    """
    with warnings.catch_warnings():
        # Suppress warnings that we can't do anything about,
        #  e.g. from aiohttp
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            module="aiohttp",
            message=".*decorator is deprecated since Python 3.8.*",
        )

        try:
            mod = __import__(mod_name)
        except ImportError:
            return False

    if not min_version:
        return mod
    else:
        import sys

        try:
            version = getattr(sys.modules[mod_name], "__version__")
        except AttributeError:
            # xlrd uses a capitalized attribute name
            version = getattr(sys.modules[mod_name], "__VERSION__")
        if version:
            from distutils.version import LooseVersion

            if LooseVersion(version) >= LooseVersion(min_version):
                return mod

    return False


def _skip_if_no_mpl():
    mod = safe_import("matplotlib")
    if mod:
        mod.use("Agg")
    else:
        return True


def _skip_if_has_locale():
    lang, _ = locale.getlocale()
    if lang is not None:
        return True


def _skip_if_not_us_locale():
    lang, _ = locale.getlocale()
    if lang != "en_US":
        return True


def _skip_if_no_scipy() -> bool:
    return not (
        safe_import("scipy.stats")
        and safe_import("scipy.sparse")
        and safe_import("scipy.interpolate")
        and safe_import("scipy.signal")
    )


# TODO: return type, _pytest.mark.structures.MarkDecorator is not public
# https://github.com/pytest-dev/pytest/issues/7469
def skip_if_installed(package: str):
    """
    Skip a test if a package is installed.

    Parameters
    ----------
    package : str
        The name of the package.
    """
    return pytest.mark.skipif(
        safe_import(package), reason=f"Skipping because {package} is installed."
    )


# TODO: return type, _pytest.mark.structures.MarkDecorator is not public
# https://github.com/pytest-dev/pytest/issues/7469
def skip_if_no(package: str, min_version: Optional[str] = None):
    """
    Generic function to help skip tests when required packages are not
    present on the testing system.

    This function returns a pytest mark with a skip condition that will be
    evaluated during test collection. An attempt will be made to import the
    specified ``package`` and optionally ensure it meets the ``min_version``

    The mark can be used as either a decorator for a test function or to be
    applied to parameters in pytest.mark.parametrize calls or parametrized
    fixtures.

    If the import and version check are unsuccessful, then the test function
    (or test case when used in conjunction with parametrization) will be
    skipped.

    Parameters
    ----------
    package: str
        The name of the required package.
    min_version: str or None, default None
        Optional minimum version of the package.

    Returns
    -------
    _pytest.mark.structures.MarkDecorator
        a pytest.mark.skipif to use as either a test decorator or a
        parametrization mark.
    """
    msg = f"Could not import '{package}'"
    if min_version:
        msg += f" satisfying a min_version of {min_version}"
    return pytest.mark.skipif(
        not safe_import(package, min_version=min_version), reason=msg
    )


skip_if_no_mpl = pytest.mark.skipif(
    _skip_if_no_mpl(), reason="Missing matplotlib dependency"
)
skip_if_mpl = pytest.mark.skipif(not _skip_if_no_mpl(), reason="matplotlib is present")
skip_if_32bit = pytest.mark.skipif(not IS64, reason="skipping for 32 bit")
skip_if_windows = pytest.mark.skipif(is_platform_windows(), reason="Running on Windows")
skip_if_windows_python_3 = pytest.mark.skipif(
    is_platform_windows(), reason="not used on win32"
)
skip_if_has_locale = pytest.mark.skipif(
    _skip_if_has_locale(), reason=f"Specific locale is set {locale.getlocale()[0]}"
)
skip_if_not_us_locale = pytest.mark.skipif(
    _skip_if_not_us_locale(), reason=f"Specific locale is set {locale.getlocale()[0]}"
)
skip_if_no_scipy = pytest.mark.skipif(
    _skip_if_no_scipy(), reason="Missing SciPy requirement"
)
skip_if_no_ne = pytest.mark.skipif(
    not USE_NUMEXPR,
    reason=f"numexpr enabled->{USE_NUMEXPR}, installed->{NUMEXPR_INSTALLED}",
)


# TODO: return type, _pytest.mark.structures.MarkDecorator is not public
# https://github.com/pytest-dev/pytest/issues/7469
def skip_if_np_lt(ver_str: str, *args, reason: Optional[str] = None):
    if reason is None:
        reason = f"NumPy {ver_str} or greater required"
    return pytest.mark.skipif(
        np.__version__ < LooseVersion(ver_str), *args, reason=reason
    )


def parametrize_fixture_doc(*args):
    """
    Intended for use as a decorator for parametrized fixture,
    this function will wrap the decorated function with a pytest
    ``parametrize_fixture_doc`` mark. That mark will format
    initial fixture docstring by replacing placeholders {0}, {1} etc
    with parameters passed as arguments.

    Parameters
    ----------
    args: iterable
        Positional arguments for docstring.

    Returns
    -------
    function
        The decorated function wrapped within a pytest
        ``parametrize_fixture_doc`` mark
    """

    def documented_fixture(fixture):
        fixture.__doc__ = fixture.__doc__.format(*args)
        return fixture

    return documented_fixture


class check_file_leaks(ContextDecorator):
    """
    Use psutil and ResourceWarning to identify forgotten resources.

    ResourceWarnings that contain the string 'ssl' are ignored as they are very likely
    caused by boto3 (GH#17058).
    """

    def __init__(self, ignore_connections: bool = False):
        super().__init__()
        self.ignore_connections = ignore_connections

    def __enter__(self):
        # catch warnings
        self.catcher = warnings.catch_warnings(record=True)
        self.record = self.catcher.__enter__()

        # get files and connections
        self.psutil = safe_import("psutil")
        if self.psutil:
            self.proc = self.psutil.Process()
            self.flist = self.proc.open_files()
            self.conns = self.proc.connections()

        return self

    def __exit__(self, *exc):
        self.catcher.__exit__(*exc)

        # re-throw warnings
        fields = ("category", "source", "filename", "lineno")
        for message in self.record:
            warnings.warn_explicit(
                message.message, **{field: getattr(message, field) for field in fields}
            )

        # assert no non-ssl ResourceWarnings
        messages = [
            warn.message
            for warn in self.record
            if issubclass(warn.category, ResourceWarning)
            and "ssl" not in str(warn.message)
        ]
        assert not messages, f"{messages}"

        # psutil
        if self.psutil:
            flist2 = self.proc.open_files()

            # on some builds open_files includes file position, which we _dont_
            # expect to remain unchanged, so we need to compare excluding that
            flist_ex = {(x.path, x.fd) for x in self.flist}
            flist2_ex = {(x.path, x.fd) for x in flist2}
            assert (
                flist2_ex == flist_ex
            ), f"{flist_ex - flist2_ex} {flist2_ex - flist_ex}"

            if not self.ignore_connections:
                conns = set(self.conns)
                conns2 = set(self.proc.connections())
                assert conns2 == conns, f"{conns - conns2} {conns2 - conns}"


def async_mark():
    try:
        import_optional_dependency("pytest_asyncio")
        async_mark = pytest.mark.asyncio
    except ImportError:
        async_mark = pytest.mark.skip(reason="Missing dependency pytest-asyncio")

    return async_mark


# Note: we are using a string as condition (and not for example
# `get_option("mode.data_manager") == "array"`) because this needs to be
# evaluated at test time (otherwise this boolean condition gets evaluated
# at import time, when the pd.options.mode.data_manager has not yet been set)

skip_array_manager_not_yet_implemented = pytest.mark.skipif(
    "config.getvalue('--array-manager')", reason="JSON C code relies on Blocks"
)

skip_array_manager_invalid_test = pytest.mark.skipif(
    "config.getvalue('--array-manager')",
    reason="Test that relies on BlockManager internals or specific behaviour",
)

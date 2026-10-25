"""Exception hierarchy for the environment suite."""

from __future__ import annotations


class EnvSuiteError(Exception):
    """Base class for every error raised by the environment suite."""


class PythonVersionError(EnvSuiteError):
    """The running interpreter does not match the pinned version."""


class VirtualEnvError(EnvSuiteError):
    """The process is not running inside the expected virtual environment."""


class EnvFileError(EnvSuiteError):
    """A .env file is malformed."""


class PreflightError(EnvSuiteError):
    """A required system CLI dependency is missing or too old."""


class ConfigError(EnvSuiteError):
    """Configuration is invalid, unknown or inconsistent."""


class HardwareError(EnvSuiteError):
    """Hardware detection or device selection failed."""


class ResourceLimitError(EnvSuiteError):
    """A memory or resource limit cannot be applied or was exceeded."""


class BinaryResolutionError(EnvSuiteError):
    """A native library or C-extension could not be resolved or loaded."""


class WorkspaceError(EnvSuiteError):
    """The ephemeral workspace is unsafe, full or unavailable."""


class SecretLeakError(EnvSuiteError):
    """Potential secrets were found in scanned content."""


class HotReloadError(EnvSuiteError):
    """The hot-reload engine was misconfigured."""

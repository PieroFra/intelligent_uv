"""Pure package-defined capabilities for the current edition.

The full GitHub build ships this capability enabled. Only the native ZIP
pins it off: the native packaging writes False into this file inside the
artifact, never through RNA, presets, or user environment settings.
"""

EXTERNAL_ENGINE_ENABLED = True

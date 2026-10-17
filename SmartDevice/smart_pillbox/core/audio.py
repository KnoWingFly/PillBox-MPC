"""Chime of a popped-up compartment.

Plays config.CHIME_SOUND_PATH (smart_pillbox/assets/chime.wav by default,
PILLCARE_CHIME_FILE overrides) through QSoundEffect, which only accepts
uncompressed PCM WAV: 16-bit, 44.1 or 48 kHz, mono or stereo, about 1-3 s.
Without a usable file it falls back to the system beep. QSoundEffect is
asynchronous, so nothing here blocks the GUI.
"""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication

from smart_pillbox import config

logger = logging.getLogger(__name__)

_effect: QSoundEffect | None = None
_effect_loaded = False


def _sound() -> QSoundEffect | None:
    """The chime, created on first use (needs the QApplication); None if there is no file."""
    global _effect, _effect_loaded
    if not _effect_loaded:
        _effect_loaded = True
        path = config.CHIME_SOUND_PATH
        if path.is_file():
            _effect = QSoundEffect(QApplication.instance())
            _effect.setSource(QUrl.fromLocalFile(str(path)))
            _effect.setVolume(config.CHIME_VOLUME)
            logger.info("Chime sound: %s", path)
        else:
            logger.info("No chime file at %s; using the system beep.", path)
    if _effect is not None and _effect.status() == QSoundEffect.Status.Error:
        return None  # not a PCM WAV (or unreadable): beep instead
    return _effect


def play_chime() -> None:
    effect = _sound()
    if effect is None:
        app = QApplication.instance()
        if app:
            app.beep()
    elif not effect.isPlaying():
        effect.play()  # plays as soon as loading finishes if it is still loading
    logger.debug("Chime sounded")


def stop_chime() -> None:
    if _effect is not None:
        _effect.stop()

"""
tests/test_tts.py - 認証コード読み上げ音声の組み立てテスト (gTTS はモック)
"""
import os
import wave

import pytest
from pydub import AudioSegment

from app import tts


@pytest.fixture
def fake_tts(monkeypatch, tmp_path):
    """gTTS を呼ばず、文言ごとに長さの違う無音を返す。呼ばれた文言を記録する。"""
    spoken: list[str] = []

    def _segment(text: str) -> AudioSegment:
        spoken.append(text)
        return AudioSegment.silent(duration=100)

    def _digits(code: str, pause_ms: int = 400) -> AudioSegment:
        spoken.append(f"<digits:{code}>")
        return AudioSegment.silent(duration=50 * len(code))

    monkeypatch.setattr(tts, "_tts_segment", _segment)
    monkeypatch.setattr(tts, "_build_digit_segments", _digits)
    monkeypatch.setattr(tts.settings, "tts_sounds_dir", str(tmp_path))
    return spoken


def _wav_info(path: str) -> tuple[int, int, int]:
    with wave.open(path, "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth()


def test_generate_otp_prompts_writes_all_files(fake_tts, tmp_path):
    files = tts.generate_otp_prompts("123456", filename_base="otp_09012341234")

    assert files == {
        "main": "telauth/otp_09012341234_main",
        "repeat": "telauth/otp_09012341234_repeat",
        "prompt_repeat": "telauth/prompt_repeat",
        "goodbye": "telauth/goodbye",
    }
    for name in files.values():
        path = tmp_path / (name.split("/", 1)[1] + ".wav")
        assert path.exists(), name
        assert _wav_info(str(path)) == (8000, 1, 2)


def test_generate_otp_prompts_wording(fake_tts):
    tts.generate_otp_prompts("123456", filename_base="otp_x")

    # 旧文言 (挨拶 / 有効期限) は含まれない
    joined = " ".join(fake_tts)
    assert "お電話ありがとうございます" not in joined
    assert "有効です" not in joined

    assert "認証コードをお伝えします。" in fake_tts
    assert "認証コードは、" in fake_tts
    assert "もう一度繰り返します。認証コードは、" in fake_tts
    assert "繰り返します。認証コードは、" in fake_tts
    assert fake_tts.count("<digits:123456>") == 2
    assert "もう一度お聞きになる場合は、シャープを押してください。" in fake_tts
    assert "ご利用ありがとうございました。" in fake_tts


def test_static_prompts_are_generated_once(fake_tts, tmp_path):
    tts.generate_otp_prompts("111111", filename_base="otp_a")
    before = len(fake_tts)
    tts.generate_otp_prompts("222222", filename_base="otp_b")
    added = fake_tts[before:]

    for text in tts.STATIC_PROMPTS.values():
        assert text not in added
    assert (tmp_path / "prompt_repeat.wav").exists()
    assert (tmp_path / "goodbye.wav").exists()

"""
app/tts.py - gTTSおよびpydubを利用した音声ファイル生成
"""
import os
import uuid
import logging
from gtts import gTTS
from pydub import AudioSegment, effects
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_digit_segments(otp_code: str, pause_ms: int = 400) -> AudioSegment:
    """
    数字をひとつずつ個別にgTTSで読み上げ、数字間に無音を挟んで結合する。
    コールセンター・ナビダイヤル風のゆっくりとした読み方を再現する。
    """
    digit_map = {
        "0": "ぜろ", "1": "いち", "2": "に", "3": "さん",
        "4": "よん", "5": "ご", "6": "ろく", "7": "なな",
        "8": "はち", "9": "きゅう"
    }
    silence = AudioSegment.silent(duration=pause_ms)
    combined = AudioSegment.silent(duration=0)

    for digit in otp_code:
        spoken = digit_map.get(digit, digit)
        tts = gTTS(text=spoken, lang="ja")
        tmp_path = f"/tmp/_digit_{uuid.uuid4().hex}.mp3"
        tts.save(tmp_path)
        seg = AudioSegment.from_mp3(tmp_path)
        os.remove(tmp_path)
        combined += seg + silence

    return combined


def _tts_segment(text: str) -> AudioSegment:
    """テキストをgTTSで読み上げてAudioSegmentを返す（変換なし）。"""
    tmp_path = f"/tmp/_tts_{uuid.uuid4().hex}.mp3"
    tts = gTTS(text=text, lang="ja")
    tts.save(tmp_path)
    seg = AudioSegment.from_mp3(tmp_path)
    os.remove(tmp_path)
    return seg


def _export_wav(segment: AudioSegment, wav_path: str) -> None:
    """Asterisk互換 (8kHz / mono / 16bit PCM) で書き出す。"""
    segment = segment.set_frame_rate(8000).set_channels(1).set_sample_width(2)
    segment.export(wav_path, format="wav")
    logger.info(f"TTSファイル生成完了: {wav_path}")


# 固定文言 (コードに依存しないので一度生成したら使い回す)
STATIC_PROMPTS = {
    # 「#」の案内。ダイヤルプランでは Background() で流し、再生中の押下も受け付ける
    "prompt_repeat": "もう一度お聞きになる場合は、シャープを押してください。",
    # 5秒応答が無いときの締め
    "goodbye": "ご利用ありがとうございました。",
}


def ensure_static_prompts() -> dict[str, str]:
    """固定文言の wav が無ければ生成する。戻り値は Playback 用の名前。"""
    os.makedirs(settings.tts_sounds_dir, exist_ok=True)
    names = {}
    for key, text in STATIC_PROMPTS.items():
        wav_path = os.path.join(settings.tts_sounds_dir, f"{key}.wav")
        if not os.path.exists(wav_path):
            _export_wav(_tts_segment(text), wav_path)
        names[key] = f"telauth/{key}"
    return names


def generate_otp_prompts(otp_code: str, filename_base: str = None) -> dict[str, str]:
    """
    認証コード読み上げ用の wav を生成する。

    生成するファイル (Playback 用の名前を dict で返す):
      main   : 「認証コードをお伝えします。」→ コード → 「もう一度繰り返します。」→ コード
      repeat : 「繰り返します。認証コードは、…です。」 (# が押されたとき用)
      prompt_repeat / goodbye : 固定文言 (ensure_static_prompts)

    案内の流れ (asterisk/extensions.conf [otp-auth]):
      main → prompt_repeat → 5秒待ち → (無応答) goodbye → 切断
                          ↘ (#) repeat → prompt_repeat → …
    """
    os.makedirs(settings.tts_sounds_dir, exist_ok=True)
    if not filename_base:
        filename_base = f"otp_{uuid.uuid4().hex}"

    long_silence = AudioSegment.silent(duration=800)
    short_silence = AudioSegment.silent(duration=300)
    mid_silence = AudioSegment.silent(duration=500)

    try:
        intro = _tts_segment("認証コードをお伝えします。")
        code_label = _tts_segment("認証コードは、")
        code_end = _tts_segment("です。")
        repeat_label = _tts_segment("もう一度繰り返します。認証コードは、")
        again_label = _tts_segment("繰り返します。認証コードは、")
        digits_first = _build_digit_segments(otp_code, pause_ms=450)
        digits_second = _build_digit_segments(otp_code, pause_ms=500)

        main = (
            intro + long_silence
            + code_label + short_silence + digits_first + code_end + mid_silence
            + repeat_label + short_silence + digits_second + code_end + long_silence
        )
        repeat = again_label + short_silence + digits_second + code_end + mid_silence

        _export_wav(main, os.path.join(settings.tts_sounds_dir, f"{filename_base}_main.wav"))
        _export_wav(repeat, os.path.join(settings.tts_sounds_dir, f"{filename_base}_repeat.wav"))
        static = ensure_static_prompts()

    except Exception as e:
        logger.error(f"TTS生成中にエラーが発生しました: {e}")
        raise

    return {
        "main": f"telauth/{filename_base}_main",
        "repeat": f"telauth/{filename_base}_repeat",
        **static,
    }

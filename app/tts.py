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


def generate_tts_wav(otp_code: str, filename_base: str = None) -> str:
    """
    OTPコードを含む日本語テキストを生成し、gTTSでmp3化後、
    Asterisk互換のwav (8kHz, mono, 16bit PCM) に変換して保存する。

    Returns:
        str: AsteriskのPlaybackアプリケーションに渡すためのファイル名
    """
    os.makedirs(settings.tts_sounds_dir, exist_ok=True)
    if not filename_base:
        filename_base = f"otp_{uuid.uuid4().hex}"

    wav_path = os.path.join(settings.tts_sounds_dir, f"{filename_base}.wav")
    interval_minutes = settings.otp_interval_seconds // 60
    long_silence = AudioSegment.silent(duration=800)
    short_silence = AudioSegment.silent(duration=300)

    try:
        # --- 冒頭案内 ---
        intro = _tts_segment(
            f"お電話ありがとうございます。{settings.service_name}でございます。"
            f"ただいま、認証番号をお伝えいたします。"
        )

        # --- 1回目 ---
        first_label = _tts_segment("認証番号は、")
        digits_first = _build_digit_segments(otp_code, pause_ms=450)
        first_end = _tts_segment("です。")

        # --- 2回目 ---
        second_label = _tts_segment("もう一度申し上げます。")
        digits_second = _build_digit_segments(otp_code, pause_ms=500)
        second_end = _tts_segment("以上でございます。")

        # --- 締め ---
        outro = _tts_segment(
            f"このコードは{interval_minutes}分間有効です。"
            "ご利用ありがとうございました。"
        )

        # --- 結合 ---
        final = (
            intro + long_silence
            + first_label + short_silence + digits_first + first_end + long_silence
            + second_label + short_silence + digits_second + second_end + long_silence
            + outro
        )

        # Asterisk互換: 8kHz・モノラル・16bit PCMに統一して書き出し
        final = final.set_frame_rate(8000).set_channels(1).set_sample_width(2)
        final.export(wav_path, format="wav")
        logger.info(f"TTSファイル生成完了: {wav_path}")

    except Exception as e:
        logger.error(f"TTS生成中にエラーが発生しました: {e}")
        raise

    return f"telauth/{filename_base}"

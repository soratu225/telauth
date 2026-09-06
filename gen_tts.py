import asyncio
import edge_tts
import subprocess
import os

text = "おはようございます。たかが怒っています。早く来てください。ご利用ありがとうございました。"

async def main():
    mp3 = '/app/data/custom_call.mp3'
    wav = '/app/data/custom_call.wav'
    await edge_tts.Communicate(text, 'ja-JP-NanamiNeural').save(mp3)
    # Asterisk用WAV(8kHz, mono, 16bit signed)に変換
    subprocess.run(['ffmpeg', '-y', '-i', mp3, '-ar', '8000', '-ac', '1', '-sample_fmt', 's16', wav], check=True, capture_output=True)
    os.remove(mp3)
    print('Done:', wav)

asyncio.run(main())

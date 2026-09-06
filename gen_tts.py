import asyncio
import edge_tts
import os

text = "おはようございます。たかが怒っています。早く来てください。ご利用ありがとうございました。"

async def main():
    # MP3として生成（ffmpegなしでも動く）
    await edge_tts.Communicate(text, 'ja-JP-NanamiNeural').save('/app/data/custom_call.mp3')
    print('MP3 Done')

asyncio.run(main())

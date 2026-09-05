# 電話OTP認証サービス (telauth)

Brastel Basix を利用して、電話でOTPを読み上げる認証サービスです。

## 特徴

- 📞 **電話でOTP読み上げ** — Brastel Basix PBX APIで発信、XML IVRのTTSでコードを読み上げ
- 🔑 **TOTP方式** — 電話番号ごとにシークレットを管理（RFC 6238準拠）
- 🔒 **暗号化ストレージ** — TOTPシークレットはFernet暗号化してDBに保存
- 🚦 **レート制限** — 同一番号への連続発信を制限（デフォルト5分に1回）
- 🛡️ **APIキー認証** — 運営者向けAPIはX-API-Keyヘッダーで保護

---

## クイックスタート

### 1. 環境設定

```bash
cp .env.example .env
# .env を編集してBrastelの認証情報を設定
```

必須設定項目:

| 変数 | 説明 |
|------|------|
| `API_KEY` | 運営者向けAPIの認証キー |
| `BRASTEL_DOMAIN` | Basixドメイン名 |
| `BRASTEL_API_TOKEN` | Basix APIトークン |
| `BRASTEL_IVR_EXTENSION` | IVR拡張番号（Basixダッシュボードで設定） |
| `IVR_CALLBACK_BASE_URL` | 外部公開されたサーバーURL（BasixがコールバックするURL） |

### 2. インストール

```bash
pip install -r requirements.txt
```

### 3. 起動

```bash
uvicorn app.main:app --reload
```

API ドキュメント: http://localhost:8000/docs

---

## Brastelダッシュボード設定

1. **IVR拡張番号の作成**
   - BasixダッシュボードでカスタムIVR拡張番号を作成
   - XML Server URLに `{IVR_CALLBACK_BASE_URL}/ivr/speak?token={IVR_SECRET_TOKEN}` を設定

2. **IVR_CALLED_NUMBER_PARAM の確認**
   - BasixがコールバックPOSTで送る「発信先電話番号」のパラメータ名を確認
   - `.env` の `IVR_CALLED_NUMBER_PARAM` に設定（デフォルト: `called_number`）

---

## 運営者向けAPI

### 発信してOTPを読み上げる

```bash
curl -X POST http://localhost:8000/api/v1/call-otp \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "09012341234"}'
```

### OTPコードを検証する

```bash
curl -X POST http://localhost:8000/api/v1/verify \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "09012341234", "code": "123456"}'
```

### 登録済み電話番号一覧

```bash
curl http://localhost:8000/api/v1/phones \
  -H "X-API-Key: your-api-key"
```

### TOTPシークレット取得（アプリ連携用）

```bash
curl http://localhost:8000/api/v1/phones/09012341234/secret \
  -H "X-API-Key: your-api-key"
```

### 電話番号を削除

```bash
curl -X DELETE http://localhost:8000/api/v1/phones/09012341234 \
  -H "X-API-Key: your-api-key"
```

---

## 着信IVRメニュー

着信すると `asterisk/sounds/ivr_menu.wav` のメニューが流れ、押されたキーで分岐します。

| キー | 動作 |
|------|------|
| `1` | 電話認証（OTP読み上げ） |
| `2` `3` `9` | 混雑案内 `asterisk/sounds/queue_notice.wav` を再生後、保留音を流し続ける（オペレーター接続は未実装） |
| `#` | メニューをもう一度再生 |
| 無入力 / 無効入力 | メニューを再生し直す（3回で切断） |

保留音は `asterisk/sounds/moh/` 内の wav をループ再生します。同梱の `hold_placeholder.wav` は仮の合成音なので、正式な保留音（8kHz / mono / 16bit wav）に差し替えてください。

音声ファイルの変換例:

```bash
ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec pcm_s16le asterisk/sounds/ivr_menu.wav
```

音声・ダイヤルプランは Asterisk イメージに焼き込まれ、起動時に entrypoint.sh がボリュームへ展開します。変更後は `docker compose build asterisk && docker compose up -d --force-recreate asterisk` で反映してください。

## 読み上げ音声の内容

```
お電話ありがとうございます。アピレンティック電話認証サービスです。
認証番号は次の通りです。
1。2。3。4。5。6。
このコードは15分間有効です。
お電話ありがとうございました。
```

---

## テスト

```bash
pytest tests/ -v
```

---

## アーキテクチャ

```
[運営者アプリ]
    |
    | POST /api/v1/call-otp  (X-API-Key認証)
    v
[telauth API サーバー]
    |
    | POST /api/initiate_call (Basic Auth)
    v
[Brastel Basix PBX]
    |
    | 発信: ユーザーの電話番号
    v
[ユーザーの電話]
    |
    | 着信接続後、BasixがXML Server URLをPOST
    v
[telauth /ivr/speak]
    |
    | DB からシークレット取得 → TOTP生成 → TTS XML返却
    v
[Brastel がTTSで読み上げ]
```

## ファイル構成

```
telauth/
├── app/
│   ├── main.py          # FastAPI エントリーポイント
│   ├── config.py        # 環境変数設定
│   ├── database.py      # SQLAlchemy設定
│   ├── models.py        # DBモデル（PhoneSecret, CallLog）
│   ├── otp.py           # TOTP生成・検証・暗号化
│   ├── brastel.py       # Basix PBX APIクライアント
│   └── routers/
│       ├── operator.py  # 運営者向けAPI
│       └── ivr.py       # IVRコールバック
├── tests/
│   ├── conftest.py      # テストフィクスチャ
│   ├── test_otp.py      # OTPユニットテスト
│   ├── test_operator.py # 運営者APIテスト
│   └── test_ivr.py      # IVRコールバックテスト
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## セキュリティ上の注意

- `SECRET_ENCRYPTION_KEY` を本番環境では必ず設定してください（未設定時は再起動でOTPが無効になります）
- `IVR_SECRET_TOKEN` を設定してIVRコールバックを保護してください
- `API_KEY` は推測困難なランダム文字列を使用してください
- 本番ではHTTPSを必ず使用してください

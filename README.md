# 電話OTP認証サービス (telauth)

Brastel の SIP 回線と Asterisk を使った電話認証サービスです。
運営者アプリが画面に認証コードを表示し、利用者がその電話番号から電話をかけてコードを入力すると、
発信者番号に紐づくコードと照合して認証します。

## 特徴

- 📞 **電話でコード入力** — 利用者が電話をかけ、画面のコードをダイヤルキーで入力（`*` で確定）
- 🔑 **TOTP方式** — 電話番号ごとにシークレットを管理（RFC 6238準拠）。他人のコードは発信者番号が違うので照合に失敗
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
| `BRASTEL_SIP_USERNAME` / `BRASTEL_SIP_PASSWORD` | Brastel の SIP アカウント |
| `INTERNAL_TOKEN` | Asterisk → API の内部呼び出しを守るトークン（推奨。空なら検査しない） |

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

## 認証の流れ

1. 運営者アプリが `POST /api/v1/code` に利用者の電話番号を渡し、返ってきた認証コードを画面に表示する
2. 利用者がその電話番号から電話をかけ、メニューで `1` を押す
3. 案内のあとの発信音（ピッ）に続けてコードを入力し、`*`（コメジルシ）で確定する
4. Asterisk が発信者番号と入力コードを `GET /api/v1/inbound-verify` に渡し、TOTP を照合する
5. 一致すれば「認証が完了しました」を流して切断。運営者アプリは `GET /api/v1/auth-status` で完了を確認する
6. 不一致なら「コードが違うようです」を流して再入力（5回で切断。API 側も有効期間内に5回失敗した番号をロック）

---

## 運営者向けAPI

### 画面に表示する認証コードを発行する

```bash
curl -X POST http://localhost:8000/api/v1/code \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "09012341234"}'
# => {"phone_number":"09012341234","code":"123456","expires_in_seconds":540}
```

### 電話での認証が完了したか確認する

```bash
curl "http://localhost:8000/api/v1/auth-status?phone_number=09012341234" \
  -H "X-API-Key: your-api-key"
# => {"phone_number":"09012341234","verified":true,"verified_at":"2026-09-06T02:30:00Z"}
```

`within_seconds` で遡る秒数を指定できます（既定はコードの有効期間）。

### 着信・認証ログを取得する

```bash
curl "http://localhost:8000/api/v1/logs?phone_number=09012341234" \
  -H "X-API-Key: your-api-key"
```

status は `inbound_answered`（着信）/ `completed`（通話終了）/ `verified`（照合成功）/ `verify_failed`（照合失敗）です。

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

着信するとすぐ応答して呼び出し音を 8 秒流してから（携帯側の音声接続の遅れを吸収するため）、`asterisk/sounds/ivr_menu.wav` のメニューが流れ、押されたキーで分岐します。

```
カスタマーサポートでございます。
電話認証をご利用の方は 1 を、アピレンティックへお問い合わせの方は 2 を、
アイズンホスティングにお問い合わせの方は 3 を、内線番号をお持ちの方は 4 を押してください。
もう一度お聞きになる場合はシャープを押してください。
```

| キー | 動作 |
|------|------|
| `1` | 電話認証（画面の認証コードを入力して `*` で確定） |
| `2` `3` | 混雑案内 `asterisk/sounds/queue_notice.wav` を再生後、保留音を流し続ける（オペレーター接続は未実装） |
| `4` | 内線（内線番号を入力して `*` で確定 → Discord で担当者を呼び出し → 担当者のブラウザで受話） |
| `#` | メニューをもう一度再生 |
| 無入力 / 無効入力 | メニューを再生し直す（3回で切断） |
| 非通知着信 | メニューの前に `asterisk/sounds/no_callerid.wav`（発信者番号を通知してかけ直すよう案内）を再生して切断 |

保留音は `asterisk/sounds/moh/` 内の wav をループ再生します。同梱の `scarlatti_k145.wav` はドメニコ・スカルラッティ「ソナタ ニ長調 K.145」の弦楽合奏版です。

- 編曲・演奏: Michel Rondeau
- 出典: [IMSLP](https://imslp.org/wiki/Keyboard_Sonata_in_D_major,_K.145_(Scarlatti,_Domenico))
- ライセンス: [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)（クレジット表記が必要）

別の曲に差し替える場合は 8kHz / mono / 16bit の wav を同じフォルダに置いてください。

音声ファイルの変換例:

```bash
ffmpeg -i input.mp3 -ar 8000 -ac 1 -acodec pcm_s16le asterisk/sounds/ivr_menu.wav
```

音声・ダイヤルプランは Asterisk イメージに焼き込まれ、起動時に entrypoint.sh がボリュームへ展開します。変更後は `docker compose build asterisk && docker compose up -d --force-recreate asterisk` で反映してください。

## 電話認証の音声

メニューで `1` を押すと、以下の順に流れます（音声は `asterisk/sounds/` の wav）。

| ファイル | 内容 |
|------|------|
| `otp_prompt.wav` | 電話認証サービスです。ピーッとなったら画面に表示されている認証コードを入力して、コメジルシを押してください。なお、他人のコードを入力することは絶対におやめください。 |
| `beep.wav` | 発信音（1kHz, 0.5秒。ffmpeg で生成） |
| `otp_success.wav` | 認証が完了しました。お電話、ありがとうございました。 |
| `otp_wrong.wav` | コードが違うようです。画面をご確認の上、もう一度入力してください。 |

- 数字キーでコードを入力し、`*` で確定します。`#` など他のキーは無視します。
- 15秒入力がなければ案内をもう一度流します。
- 照合失敗と無入力をあわせて 5 回で切断します。

## 内線（メニュー 4）

内線番号を押すと担当者の Discord に DM が届き、「出る」を押した人がブラウザで電話に出られます。
通話は Asterisk 自前の WebRTC（SIP over WebSocket + DTLS-SRTP）で、外部の会議サービスは使いません。

```
発信者: 4 → 内線番号 + *          担当者 (Discord DM)
   │                                📞 080-1234-5678 からお電話です！   [出る] [拒否]
   │ 「担当者を呼び出しています」                 │
   │  保留音 (最大 3 分)                          │ 「出る」→ 担当者用アカウント web1..webN を割り当て
   │                                              │   自分の DM にだけ「通話に参加」リンク
   │                                              │   他の人の DM は「○○さんが対応中」に編集
   │                                              ▼
   │                                    通話ページ (JsSIP) が wss://.../ws で Asterisk に登録
   └─ Asterisk が PJSIP/webN へ Dial ─── 通話 ─── ブラウザが自動応答
```

- 「出る」のあと担当者がページを開いて登録されるまで最大 90 秒待ちます（その間も保留音）。
- 全員が「拒否」、または 3 分応答がなければ「申し訳ありませんが、後ほどお掛け直しください」を流して切断します。DM は「応答なし」に編集されます。
- 受付時間は `EXTENSION_HOURS_START`〜`EXTENSION_HOURS_END`（既定 9〜22 時、`Asia/Tokyo`）。時間外は Discord に送らず案内して切断します。
- 通話が終わると担当者の DM は「通話が終了しました」に編集されます。
- 一覧は `GET /api/v1/extension-calls`（X-API-Key）で取れます。

### 内線番号と担当者

`extensions.json` に内線番号ごとの担当者（Discord ユーザーID）を書きます。複数人可。

```json
{
  "101": {"label": "内線101", "discord_user_ids": ["1077866390217822260", "..."]},
  "102": {"label": "内線102", "discord_user_ids": ["586379371510497340"]}
}
```

### 必要な設定（.env）

| 変数 | 内容 |
|------|------|
| `DISCORD_BOT_TOKEN` | Discord Developer Portal で作った Bot のトークン。Bot を担当者と同じサーバーに招待しておく（DM はサーバーを共有していないと届かない） |
| `PUBLIC_BASE_URL` | 担当者が開く通話ページの URL。ブラウザのマイク利用と wss のため **https 必須** |
| `TUNNEL_TOKEN` | 通話ページを https で公開する Cloudflare Tunnel のトークン（下記） |
| `WEBRTC_SECRET` | 担当者用 SIP アカウント（web1..webN）のパスワードの元。空なら `INTERNAL_TOKEN` を使う |
| `WEBRTC_SLOTS` | 同時に受けられる担当者数（既定 8） |
| `PUBLIC_IP` | サーバーの公開 IP。空なら起動時に自動検出。NAT 内でも WebRTC の音声が通るように SDP と ICE 候補に使う |

### https での公開（Cloudflare Tunnel）

ブラウザはマイクの利用と `wss://` 接続に https を要求するので、通話ページを https で公開する必要があります。
Cloudflare にドメインがあれば Tunnel が一番簡単です（ルーターのポート開放は不要）。

1. Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel（Cloudflared）
2. Public hostname に `telauth.example.com` → `HTTP` `localhost:8000` を追加（WebSocket もこの 1 本で通ります）
3. 表示されたトークンを `.env` の `TUNNEL_TOKEN` に、URL を `PUBLIC_BASE_URL` に入れる
4. `docker compose --profile tunnel up -d`

音声（RTP）は Tunnel を通らず、ルーターで転送済みの UDP 10000〜10020 を使います。

### 仕組み（Asterisk 側）

- `http.conf` で 127.0.0.1:8088 に WebSocket を開き、FastAPI の `/ws` がブラウザからの `wss` を中継します。Asterisk のポートは外に出しません。
- `pjsip.conf` の `[transport-ws]` と `webrtc=yes` のテンプレートから、`entrypoint.sh` が起動時に `web1`〜`webN` のアカウントを生成します。パスワードは `sha256("<WEBRTC_SECRET>:<slot>")` の先頭 32 文字で、API 側も同じ計算で通話ページに埋め込みます。
- `rtp.conf` の `[ice_host_candidates]` に「ローカル IP => 公開 IP」を書き足し、NAT 内でも正しい ICE 候補を出します。
- ブラウザ側は JsSIP（`app/static/jssip-3.13.8.min.js`、esbuild で単一ファイル化）で登録と自動応答を行います。

### 音声

| ファイル | 内容 |
|------|------|
| `ext_prompt.wav` | 内線番号を入力して、コメジルシを押してください。 |
| `ext_ringing.wav` | 担当者を呼び出しています。そのままお待ちください。 |
| `ext_callback.wav` | 申し訳ありませんが、後ほどお掛け直しください。 |
| `ext_closed.wav` | 内線の受付時間は、午前9時から午後10時までです。申し訳ありませんが、受付時間内にお掛け直しください。 |

この 4 つは macOS の音声合成（Kyoko）で作った仮の音声です。本番用の録音に差し替える場合は同じファイル名で 8kHz / mono / 16bit の wav を置いてください。

---

## テスト

```bash
pytest tests/ -v
```

---

## アーキテクチャ

```
[運営者アプリ]                          [利用者の電話]
    |                                        |
    | POST /api/v1/code (X-API-Key)          | 発信 → Brastel → Asterisk (メニューで 1)
    | → 認証コードを画面に表示               |
    |                                        v
    |                              [Asterisk ダイヤルプラン otp-auth]
    |                                 案内 → ピッ → 数字を収集 → * で確定
    |                                        |
    |                                        | GET /api/v1/inbound-verify?phone_number=&code=
    |                                        v
    |                              [telauth API サーバー]
    |                                 発信者番号のシークレットで TOTP 照合 → CallLog に記録
    |                                        |
    | GET /api/v1/auth-status (X-API-Key)    | 200 → 「認証が完了しました」/ 401 → 「コードが違うようです」
    | → verified=true で認証完了            v
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
│   ├── asterisk_ami.py  # Asterisk AMI クライアント（アウトバウンド用、現在未使用）
│   ├── extension_calls.py # 内線呼び出し（Discord 通知 → 応答 → ブラウザ受話のスロット割り当て）
│   ├── discord_bot.py   # Discord Bot（DM 送信とボタン処理）
│   ├── notify.py        # 通知の抽象化（テストでは差し替え）
│   └── routers/
│       ├── operator.py  # 運営者向けAPI + Asterisk 内部呼び出し
│       └── extension.py # 内線 API + 担当者用の通話ページ + /ws 中継
│   └── static/jssip-3.13.8.min.js # 通話ページ用 JsSIP
├── asterisk/
│   ├── extensions.conf  # ダイヤルプラン（IVRメニュー / 電話認証 / 内線）
│   ├── pjsip.conf.template  # Brastel + 担当者ブラウザ (WebRTC) のテンプレート
│   ├── http.conf        # SIP over WebSocket (127.0.0.1:8088)
│   └── sounds/          # メニュー・案内音声 (wav 8kHz mono)
├── extensions.json      # 内線番号 → 担当者 Discord ユーザーID
├── tests/
│   ├── conftest.py      # テストフィクスチャ
│   ├── test_operator.py # API テスト
│   ├── test_extension.py # 内線のテスト（Discord はフェイク）
│   └── test_ws_proxy.py  # /ws 中継のテスト
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

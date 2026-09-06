#!/bin/sh
set -e

SRC=/opt/telauth/etc
ETC=/etc/asterisk
IVR_SOUNDS=/var/lib/asterisk/sounds/ivr

# 設定ファイルをイメージ内のコピー元からボリュームへ展開 (常に最新のリポジトリ内容で上書き)
cp "$SRC/extensions.conf"  "$ETC/extensions.conf"
cp "$SRC/musiconhold.conf" "$ETC/musiconhold.conf"
cp "$SRC/rtp.conf"         "$ETC/rtp.conf"
cp "$SRC/logger.conf"      "$ETC/logger.conf"
cp "$SRC/http.conf"        "$ETC/http.conf"

# テンプレートから設定ファイルを作成
cp "$SRC/pjsip.conf.template"   "$ETC/pjsip.conf"
cp "$SRC/manager.conf.template" "$ETC/manager.conf"

# 公開 IP (NAT の外側) とローカル IP。WebRTC の ICE 候補と SDP に使う
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP=$(curl -s -m 5 https://api.ipify.org || true)
fi
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "telauth: PUBLIC_IP=${PUBLIC_IP:-<unknown>} LOCAL_IP=${LOCAL_IP:-<unknown>}"

# 環境変数をテンプレートに展開する (sed の区切りは | 。値に含まれる | & \ はエスケープ)
subst() {  # subst <file> <VAR>
  eval "raw=\${$2}"
  val=$(printf '%s' "$raw" | sed -e 's/[|&\\]/\\&/g')
  sed -i "s|\${$2}|$val|g" "$1"
}
subst "$ETC/pjsip.conf" BRASTEL_SIP_USERNAME
subst "$ETC/pjsip.conf" BRASTEL_SIP_PASSWORD
subst "$ETC/pjsip.conf" BRASTEL_SIP_SERVER
subst "$ETC/pjsip.conf" PUBLIC_IP

subst "$ETC/manager.conf" ASTERISK_AMI_PASSWORD

# 公開 IP が分からなければ external_* 行は外す (空だと pjsip が読み込みに失敗する)
if [ -z "$PUBLIC_IP" ]; then
  sed -i '/^external_media_address=$/d; /^external_signaling_address=$/d' "$ETC/pjsip.conf"
else
  printf '\n[ice_host_candidates]\n%s => %s\n' "$LOCAL_IP" "$PUBLIC_IP" >> "$ETC/rtp.conf"
fi

# 担当者ブラウザ用の SIP アカウント web1..webN を生成 (API 側 app/extension_calls.py と同じパスワード計算)
WEBRTC_SLOTS=${WEBRTC_SLOTS:-8}
WEBRTC_SECRET=${WEBRTC_SECRET:-${INTERNAL_TOKEN:-changeme}}
i=1
while [ "$i" -le "$WEBRTC_SLOTS" ]; do
  slot="web$i"
  pass=$(printf '%s' "$WEBRTC_SECRET:$slot" | sha256sum | cut -c1-32)
  cat >> "$ETC/pjsip.conf" <<EOF

[$slot](webrtc-endpoint)
aors=$slot
auth=$slot
callerid="$slot" <$slot>

[$slot](webrtc-aor)

[$slot](webrtc-auth)
username=$slot
password=$pass
EOF
  i=$((i + 1))
done

# IVR音声 (メニュー / 混雑案内 / 保留音) を sounds ボリュームへ展開
rm -rf "$IVR_SOUNDS"
mkdir -p "$IVR_SOUNDS"
cp -r /opt/telauth/sounds/. "$IVR_SOUNDS/"

# 権限の調整
chown -R asterisk:asterisk "$ETC" "$IVR_SOUNDS"

# Asteriskの起動
exec asterisk -f -U asterisk -G asterisk

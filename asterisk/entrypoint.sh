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

# テンプレートから設定ファイルを作成
cp "$SRC/pjsip.conf.template"   "$ETC/pjsip.conf"
cp "$SRC/manager.conf.template" "$ETC/manager.conf"

# 環境変数をテンプレートに展開する (sed の区切りは | 。値に含まれる | & \ はエスケープ)
: "${REALTIMEKIT_SIP_HOST:=sip.dyte.io}"
subst() {  # subst <file> <VAR>
  eval "raw=\${$2}"
  val=$(printf '%s' "$raw" | sed -e 's/[|&\\]/\\&/g')
  sed -i "s|\${$2}|$val|g" "$1"
}
subst "$ETC/pjsip.conf" BRASTEL_SIP_USERNAME
subst "$ETC/pjsip.conf" BRASTEL_SIP_PASSWORD
subst "$ETC/pjsip.conf" BRASTEL_SIP_SERVER
subst "$ETC/pjsip.conf" REALTIMEKIT_SIP_HOST
subst "$ETC/pjsip.conf" REALTIMEKIT_SIP_USERNAME
subst "$ETC/pjsip.conf" REALTIMEKIT_SIP_PASSWORD

subst "$ETC/manager.conf" ASTERISK_AMI_PASSWORD

# IVR音声 (メニュー / 混雑案内 / 保留音) を sounds ボリュームへ展開
rm -rf "$IVR_SOUNDS"
mkdir -p "$IVR_SOUNDS"
cp -r /opt/telauth/sounds/. "$IVR_SOUNDS/"

# 権限の調整
chown -R asterisk:asterisk "$ETC" "$IVR_SOUNDS"

# Asteriskの起動
exec asterisk -f -U asterisk -G asterisk

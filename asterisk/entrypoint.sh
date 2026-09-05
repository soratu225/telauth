#!/bin/sh
set -e

SRC=/opt/telauth/etc
ETC=/etc/asterisk
IVR_SOUNDS=/var/lib/asterisk/sounds/ivr

# 設定ファイルをイメージ内のコピー元からボリュームへ展開 (常に最新のリポジトリ内容で上書き)
cp "$SRC/extensions.conf"  "$ETC/extensions.conf"
cp "$SRC/musiconhold.conf" "$ETC/musiconhold.conf"
cp "$SRC/rtp.conf"         "$ETC/rtp.conf"

# テンプレートから設定ファイルを作成
cp "$SRC/pjsip.conf.template"   "$ETC/pjsip.conf"
cp "$SRC/manager.conf.template" "$ETC/manager.conf"

# sedを使って環境変数を置換 (追加パッケージ不要)
sed -i "s/\${BRASTEL_SIP_USERNAME}/$BRASTEL_SIP_USERNAME/g" "$ETC/pjsip.conf"
sed -i "s/\${BRASTEL_SIP_PASSWORD}/$BRASTEL_SIP_PASSWORD/g" "$ETC/pjsip.conf"
sed -i "s/\${BRASTEL_SIP_SERVER}/$BRASTEL_SIP_SERVER/g" "$ETC/pjsip.conf"

sed -i "s/\${ASTERISK_AMI_PASSWORD}/$ASTERISK_AMI_PASSWORD/g" "$ETC/manager.conf"

# IVR音声 (メニュー / 混雑案内 / 保留音) を sounds ボリュームへ展開
rm -rf "$IVR_SOUNDS"
mkdir -p "$IVR_SOUNDS"
cp -r /opt/telauth/sounds/. "$IVR_SOUNDS/"

# 権限の調整
chown -R asterisk:asterisk "$ETC" "$IVR_SOUNDS"

# Asteriskの起動
exec asterisk -f -U asterisk -G asterisk

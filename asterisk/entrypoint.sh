#!/bin/sh
set -e

# テンプレートから設定ファイルを作成
cp /etc/asterisk/pjsip.conf.template /etc/asterisk/pjsip.conf
cp /etc/asterisk/manager.conf.template /etc/asterisk/manager.conf

# sedを使って環境変数を置換 (追加パッケージ不要)
sed -i "s/\${BRASTEL_SIP_USERNAME}/$BRASTEL_SIP_USERNAME/g" /etc/asterisk/pjsip.conf
sed -i "s/\${BRASTEL_SIP_PASSWORD}/$BRASTEL_SIP_PASSWORD/g" /etc/asterisk/pjsip.conf
sed -i "s/\${BRASTEL_SIP_SERVER}/$BRASTEL_SIP_SERVER/g" /etc/asterisk/pjsip.conf

sed -i "s/\${ASTERISK_AMI_PASSWORD}/$ASTERISK_AMI_PASSWORD/g" /etc/asterisk/manager.conf

# 権限の調整
chown asterisk:asterisk /etc/asterisk/pjsip.conf
chown asterisk:asterisk /etc/asterisk/manager.conf

# Asteriskの起動
exec asterisk -f -U asterisk -G asterisk

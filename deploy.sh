#!/usr/bin/env bash
# deploy.sh
# Usage: ./deploy.sh
# 
# 192.168.0.96 (VPS/Server) へのデプロイを行います。

HOST="192.168.0.96"
USER="sdj"
# ※ パスワード(nakadashi0721) はSSH/SCP実行時に手動入力するか、sshpassを利用します

echo "ファイルを転送しています..."
scp -r ./app ./asterisk ./tests ./.env.example ./docker-compose.yml ./Dockerfile* ./requirements.txt ${USER}@${HOST}:~/telauth/

echo "リモートサーバーでDocker Composeを起動しています..."
ssh ${USER}@${HOST} "cd ~/telauth && cp -n .env.example .env && docker-compose build && docker-compose up -d"

echo "デプロイ完了！"
echo "サーバー上でステータスを確認するには以下のコマンドを実行してください："
echo "ssh ${USER}@${HOST} 'cd ~/telauth && docker-compose logs -f'"

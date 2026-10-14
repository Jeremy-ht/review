#!/usr/bin/env bash
# 从本机（Git Bash / Linux / macOS）把 site/ 推送到 Linux 云服务器
#
# 用法:
#   ./deploy/deploy.sh root@1.2.3.4                    # 全量部署（含图片）
#   SKIP_IMAGES=1 ./deploy/deploy.sh root@1.2.3.4      # 不含 images/（图片已上传到文件服务器时）
#   ./deploy/deploy.sh root@1.2.3.4 /data/www/gator    # 指定服务器上的目标目录（默认 /var/www/gator）
#
# 前提: 本机能 ssh 免密登录服务器（ssh-copy-id root@1.2.3.4 配一次）
set -euo pipefail

SERVER=${1:?"用法: deploy/deploy.sh user@host [目标目录]"}
DEST=${2:-/var/www/gator}

cd "$(dirname "$0")/.."   # 进入项目根

echo "== 打包 site/ ..."
OPTS=()
if [ "${SKIP_IMAGES:-0}" = "1" ]; then
  OPTS+=(--exclude='site/images')
  echo "   (跳过 images/，图片走文件服务器)"
fi
tar czf /tmp/gator-site.tgz "${OPTS[@]}" -C . site

echo "== 上传 $(du -h /tmp/gator-site.tgz | cut -f1) ..."
scp -q /tmp/gator-site.tgz "$SERVER:/tmp/"

echo "== 服务器端解压 ..."
ssh "$SERVER" "mkdir -p '$DEST' && tar xzf /tmp/gator-site.tgz -C '$DEST' --strip-components=1 && rm -f /tmp/gator-site.tgz"

echo "== 完成: $SERVER:$DEST"
echo "   若首次部署，别忘了配置 Nginx（deploy/nginx.conf.example）并 reload"

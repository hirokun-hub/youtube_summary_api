#!/bin/sh
set -e

# Tailscale起動スクリプト
# 要件: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 4.7, 4.8

echo "Starting tailscaled..."
# tailscaledをバックグラウンドで起動
tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &

# tailscaledの起動を待機
sleep 2

echo "Checking for existing Tailscale state..."
# 要件2.5: 既存の認証状態が存在するか確認
if [ -f "/var/lib/tailscale/tailscaled.state" ] && [ -s "/var/lib/tailscale/tailscaled.state" ]; then
    echo "Existing state found. Checking connection status..."
    
    # 要件2.7: tailscale statusで接続状態を確認
    if tailscale status --socket=/var/run/tailscale/tailscaled.sock > /dev/null 2>&1; then
        # 要件2.8: 成功（終了コード0）かつTailnetに接続済みの場合、tailscale upをスキップ
        echo "Already connected to Tailnet. Skipping 'tailscale up'."
    else
        # 要件2.9: 失敗（非0終了コード）または未接続の場合、tailscale upを再実行
        echo "Connection failed. Re-authenticating with Tailnet..."
        
        # 要件2.10: TAILSCALE_AUTH_KEYが未設定かつ既存認証状態がない場合はエラー
        if [ -z "$TAILSCALE_AUTH_KEY" ]; then
            echo "ERROR: TAILSCALE_AUTH_KEY is not set and connection failed."
            exit 1
        fi
        
        # tailscale upで再接続
        tailscale up \
            --socket=/var/run/tailscale/tailscaled.sock \
            --authkey="$TAILSCALE_AUTH_KEY" \
            --hostname="$TAILSCALE_HOSTNAME"
        
        echo "Re-authentication successful."
    fi
else
    # 要件2.6: 既存の認証状態が存在しない場合、tailscale upを実行
    echo "No existing state found. Authenticating with Tailnet..."
    
    # 要件2.10: TAILSCALE_AUTH_KEYが未設定の場合はエラー
    if [ -z "$TAILSCALE_AUTH_KEY" ]; then
        echo "ERROR: TAILSCALE_AUTH_KEY is not set. Cannot authenticate."
        exit 1
    fi
    
    # tailscale upで初回接続
    tailscale up \
        --socket=/var/run/tailscale/tailscaled.sock \
        --authkey="$TAILSCALE_AUTH_KEY" \
        --hostname="$TAILSCALE_HOSTNAME"
    
    echo "Authentication successful."
fi

echo "Tailscale is ready."
echo "Tailnet status:"
tailscale status --socket=/var/run/tailscale/tailscaled.sock

# tailscaledプロセスをフォアグラウンドで維持
wait

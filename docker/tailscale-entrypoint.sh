#!/bin/sh
set -e

# Tailscale起動スクリプト
# 要件: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 4.7, 4.8

# ソケットパスを環境変数で設定
export TS_SOCKET=/var/run/tailscale/tailscaled.sock

# エラーハンドリング関数（デバッグ用に30秒待機後に終了）
handle_auth_error() {
    echo "=========================================="
    echo "ERROR: Tailscale authentication failed."
    echo "Please check your TAILSCALE_AUTH_KEY in .env.local"
    echo "Waiting 30 seconds before exit for log inspection..."
    echo "=========================================="
    sleep 30
    exit 1
}

echo "Starting tailscaled..."
# tailscaledをバックグラウンドで起動
tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=$TS_SOCKET &

# tailscaledの起動を待機（ソケットが作成されるまで）
echo "Waiting for tailscaled to start..."
for i in $(seq 1 30); do
    if [ -S "$TS_SOCKET" ]; then
        echo "tailscaled socket is ready."
        break
    fi
    sleep 1
done

if [ ! -S "$TS_SOCKET" ]; then
    echo "ERROR: tailscaled socket not found after 30 seconds."
    handle_auth_error
fi

echo "Checking for existing Tailscale state..."
# 要件2.5: 既存の認証状態が存在するか確認
if [ -f "/var/lib/tailscale/tailscaled.state" ] && [ -s "/var/lib/tailscale/tailscaled.state" ]; then
    echo "Existing state found. Checking connection status..."
    
    # 要件2.7: tailscale statusで接続状態を確認（--socket明示）
    if tailscale --socket=$TS_SOCKET status > /dev/null 2>&1; then
        # 要件2.8: 成功（終了コード0）かつTailnetに接続済みの場合、tailscale upをスキップ
        echo "Already connected to Tailnet. Skipping 'tailscale up'."
    else
        # 要件2.9: 失敗（非0終了コード）または未接続の場合、tailscale upを再実行
        echo "Connection failed. Re-authenticating with Tailnet..."
        
        # 要件2.10: TAILSCALE_AUTH_KEYが未設定かつ既存認証状態がない場合はエラー
        if [ -z "$TAILSCALE_AUTH_KEY" ]; then
            echo "ERROR: TAILSCALE_AUTH_KEY is not set and connection failed."
            handle_auth_error
        fi
        
        # tailscale upで再接続（--socket明示）
        if ! tailscale --socket=$TS_SOCKET up \
            --authkey="$TAILSCALE_AUTH_KEY" \
            --hostname="${TAILSCALE_HOSTNAME:-youtube-api-dev}"; then
            echo "ERROR: tailscale up command failed."
            handle_auth_error
        fi
        
        echo "Re-authentication successful."
    fi
else
    # 要件2.6: 既存の認証状態が存在しない場合、tailscale upを実行
    echo "No existing state found. Authenticating with Tailnet..."
    
    # 要件2.10: TAILSCALE_AUTH_KEYが未設定の場合はエラー
    if [ -z "$TAILSCALE_AUTH_KEY" ]; then
        echo "ERROR: TAILSCALE_AUTH_KEY is not set. Cannot authenticate."
        handle_auth_error
    fi
    
    # tailscale upで初回接続（--socket明示）
    if ! tailscale --socket=$TS_SOCKET up \
        --authkey="$TAILSCALE_AUTH_KEY" \
        --hostname="${TAILSCALE_HOSTNAME:-youtube-api-dev}"; then
        echo "ERROR: tailscale up command failed."
        handle_auth_error
    fi
    
    echo "Authentication successful."
fi

echo "Tailscale is ready."
echo "Tailnet status:"
tailscale --socket=$TS_SOCKET status

# tailscaledプロセスをフォアグラウンドで維持
wait

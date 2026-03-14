# Windows Activity Logger

Windows の操作ログを収集・可視化して業務効率化を支援するツール。

## 機能（プロトタイプ）

| 機能 | 状態 |
|------|------|
| アクティブウィンドウ監視 (5秒間隔) | ✅ |
| CSV 出力 (タイムスタンプ・アプリ名・タイトル・秒数・カテゴリ) | ✅ |
| カテゴリ別サマリー / バーグラフ | ✅ |
| 無駄パターン検出 (頻繁な切り替え・長時間利用・繰り返しアクセス) | ✅ |
| 自動化提案 | ✅ |
| Google カレンダー連携 | 🔜 次フェーズ |

## クイックスタート

```bash
# 依存パッケージのインストール (Windows のみ)
pip install -r windows_activity_logger/requirements.txt

# 起動
python windows_activity_logger/main.py
```

> **Note**: `pywin32` は Windows 専用です。
> 非 Windows 環境ではモックデータで動作確認できます。

## ファイル構成

```
windows_activity_logger/
├── main.py             # エントリポイント
├── logger.py           # コア: ウィンドウ監視 & CSV 出力
├── pattern_detector.py # 無駄パターン検出 & 自動化提案
├── ui.py               # tkinter UI (3タブ)
└── requirements.txt
logs/
└── activity_YYYYMMDD_HHMMSS.csv  # 自動生成
```

## UI の使い方

1. **「▶ 記録開始」** ボタンを押すと監視開始
2. **「ログ一覧」タブ**: リアルタイムで操作ログを確認
3. **「サマリー」タブ**: カテゴリ別・アプリ別の使用時間を可視化
4. **「インサイト」タブ**: 無駄パターンと自動化提案を確認
5. **「📂 ログを開く」**: CSV が保存されたフォルダを開く

## ロードマップ

- [ ] Google カレンダー API 連携 (タスクと操作ログの紐付け)
- [ ] 日報・週報の自動生成
- [ ] スクリーンショットの定期取得 (プライバシー設定付き)
- [ ] より高度な ML ベースのパターン検出

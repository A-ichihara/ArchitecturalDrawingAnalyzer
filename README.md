# 建築図面解析・設備設計支援システム

建築図面（CAD / PDF）を設備設計で利用可能な構造化データへ変換するための基盤ツール群です。

## 概要

```text
CAD/PDF（DXF・PDF・画像）
        ↓
  建築図面解析基盤
        ↓
 ┌──────┴────────┐
 ↓               ↓
部屋情報解析      図面差分比較
 ↓               ↓
部屋名・面積      建築変更箇所
 └──────┬────────┘
        ↓
   設備設計データ（換気計算・機器選定）
```

## 設計方針

- **アルゴリズム優先**: 座標計算・幾何演算は通常のアルゴリズムで処理し、AIは部屋名の意味判定など補助用途のみ
- **セキュリティ**: 建築図面データを外部AIサービスへ送信しない（ローカル処理を優先）
- **無料・オープンソース**: ezdxf, Shapely, PyMuPDF 等の OSS ライブラリを使用
- **拡張性**: 共通インターフェースで各エンジン（OCR・AI等）を差し替え可能な設計

## プロジェクト構成

```text
ArchitecturalDrawingAnalyzer/
├── core/                  # 共通基盤モジュール
│   ├── models/            # データモデル（Drawing, Room, Change, OCRResult）
│   ├── coordinate/        # 座標系変換（CAD ↔ PDF ↔ 画像 ↔ 共通mm座標）
│   ├── geometry/          # 幾何演算エンジン（Shapely ラッパー）
│   ├── parser/            # 図面パーサー（DXF, PDF, 画像）
│   ├── ocr/               # OCRエンジン（Tesseract, PaddleOCR, EasyOCR）
│   └── ai/                # AI補助エンジン（ローカル・無効化可能）
├── apps/                  # 各アプリケーション
│   ├── room_analyzer/     # App 01: 建築図面解析
│   └── drawing_diff/      # App 02: 図面差分比較
├── data/                  # プロジェクトデータ（.gitignore 除外）
├── tests/                 # ユニットテスト
├── docs/                  # 開発ドキュメント・開発ログ
└── requirements.txt
```

## セットアップ

### 必要要件

- Python 3.9 以上
- Windows 10/11

### インストール

```powershell
# 仮想環境の作成とアクティベート
python -m venv venv
.\venv\Scripts\Activate.ps1

# 依存ライブラリのインストール
# ※フォルダパスに絵文字が含まれる場合は以下の環境変数設定が必要
$env:PYTHONIOENCODING="utf-8"
pip install -r requirements.txt
```

### アプリケーションの起動

```powershell
# Python環境から直接起動
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python.exe main.py

# または生成済みEXE（スタンドアロン）から起動
.\dist\ArchitecturalDrawingAnalyzer\ArchitecturalDrawingAnalyzer.exe
```

### EXEのビルド

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\python.exe scripts/build_exe.py
```

### テスト実行

```powershell
$env:PYTHONIOENCODING="utf-8"
.\venv\Scripts\pytest -v
```

## 開発フェーズ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 0 | プロジェクト基盤設計・構築 | ✅ 完了 |
| Phase 1 | DXF図面Viewer（画面表示・操作・EXE化） | ✅ 完了 |
| Phase 2 | DXF図面の構造化・要素情報解析（3ペインUI・幾何プロパティ計算） | ✅ 完了 |
| Phase 3 | 単線壁・部屋認識 | 未着手 |
| Phase 4 | 複線壁・壁芯算定 | 未着手 |
| Phase 5 | 部屋名と部屋領域の紐付け | 未着手 |
| Phase 6 | PDF対応 | 未着手 |
| Phase 7 | OCR | 未着手 |
| Phase 8 | AI補助 | 未着手 |
| Phase 9 | 建築図面差分比較 | 未着手 |
| Phase 10 | 設備設計データ連携 | 未着手 |

## 開発ログ・作業時間記録

詳細は [development_log.md](development_log.md) を参照。
各フェーズの修正経緯および累計作業時間を記録しています。



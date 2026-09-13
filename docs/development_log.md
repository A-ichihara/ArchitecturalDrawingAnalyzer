# 建築図面解析基盤 開発ログ

---

## Phase 0 — プロジェクト基盤設計・構築

**実施日**: 2026-08-31  
**所要時間**: 約 60 分（ライブラリのダウンロード時間を含む）  
**担当**: Antigravity AI + ユーザー承認

---

### 実施内容

1. **プロジェクト構成の設計・作成**
   - `core/`, `apps/`, `data/`, `tests/`, `docs/` という階層構造を新規作成
   - 各サブパッケージに `__init__.py` を配置し、Pythonパッケージとして管理可能にした

2. **Python仮想環境の構築**
   - `python -m venv venv` で仮想環境を作成
   - `requirements.txt` を定義し、依存ライブラリを一括インストール
   - **注意**: フォルダ名に絵文字 `💻️` が含まれるため、pipの標準出力でUnicodeEncodeError (cp932) が発生することが判明。
     環境変数 `PYTHONIOENCODING=utf-8` を設定することで回避。今後の運用でも設定が必要。

3. **インストール済みライブラリ**

   | ライブラリ | バージョン | 用途 | ライセンス |
   |-----------|-----------|------|-----------|
   | ezdxf | 1.4.2 | DXFファイルの解析 | MIT |
   | shapely | 2.0.7 | 幾何計算（交差・面積・バッファ等） | BSD |
   | PySide6 | 6.10.3 | GUIフレームワーク（将来のビューア用） | LGPL |
   | PyMuPDF | 1.26.5 | PDFのベクトル要素・テキスト抽出 | AGPL / Commercial |
   | pdfplumber | 0.11.8 | PDF解析補助 | MIT |
   | Pillow | 11.3.0 | 画像処理 | HPND (MIT系) |
   | numpy | 2.0.2 | 数値計算・アフィン変換行列 | BSD |
   | pytest | 8.4.2 | ユニットテスト | MIT |

   > [!WARNING]
   > **PyMuPDFのライセンス注意**: PyMuPDF はデフォルトで AGPLv3 ライセンスです。
   > 商用・社内ツール等でクローズドな利用を行う場合は、商用ライセンスの取得が必要か確認すること。
   > オープンソース代替として `pdfplumber` のみに絞ることも検討可能。

4. **共通データモデルの実装** (`core/models/`)
   - `Drawing`: 図面全体のメタデータと要素リスト
   - `DrawingElement` (基底クラス) + 派生: `LineElement`, `PolylineElement`, `TextElement`, `CircleElement`, `ArcElement`
   - `Room`: 部屋情報（将来の換気計算に必要な `ceiling_height`, `volume`, `occupants`, `required_ventilation` を `properties` で拡張可能）
   - `Change`: 図面差分情報
   - `OCRResult`: OCR認識結果

5. **座標変換モジュールの実装** (`core/coordinate/transformer.py`)
   - `CoordinateTransformer` クラスを設計
   - 共通座標系 = **現実世界のmm単位、デカルト座標（左下原点）**
   - `from_cad()`, `from_pdf()`, `from_image()` のクラスメソッドで各ファイル形式用の変換器を生成
   - numpyの3×3アフィン変換行列で移動・回転・スケーリングを統一的に扱う

6. **Geometry Engine の実装** (`core/geometry/engine.py`)
   - 抽象クラス `IGeometryEngine` と実装クラス `ShapelyGeometryEngine` を定義
   - 実装メソッド:
     - `line_intersection()` — 線分交差判定・交点取得
     - `line_distance()` — 線分間の最短距離
     - `is_parallel()` — 平行線判定（角度許容誤差付き）
     - `calculate_polygon_area()` — ポリゴン面積計算
     - `polygon_buffer()` — ポリゴンバッファ処理
     - `intersects()` — 重なり判定
     - `compute_wall_centerline()` — 複線壁から壁芯を抽出
     - `extend_line()` — 線分延長
     - `split_line()` — 線分分割

7. **各種エンジンのインターフェースとスタブ実装**
   - Parser: `IDrawingParser` + `DxfParser`, `PdfParser`, `ImageParser` (スタブ)
   - OCR: `IOcrEngine` + `TesseractOcrEngine`, `PaddleOcrEngine`, `EasyOcrEngine` (スタブ)
   - AI: `IAiEngine` + `NullAiEngine` (ルールベース), `LocalAiEngine` (スタブ)
   - **設計方針**: AIを無効化 (`NullAiEngine`) しても基本動作が可能な構造を採用

8. **ユニットテストの実装と動作確認** (`tests/`)
   - 24件全件パス (1.79秒)
   - `test_models.py`, `test_coordinate.py`, `test_geometry.py`, `test_parser.py`, `test_ocr.py`, `test_ai.py`

9. **バグ修正**
   - `drawing.py` の各サブクラス `from_dict()` で `element_type` を誤って pop していたため、
     デシリアライズ時に `TypeError` が発生した。`element_type` はコンストラクタに必要なため、
     `__post_init__` で上書きする構造に変更して修正。

---

### 決定事項・設計上の判断

- **共通座標系**: mm単位・デカルト座標系（左下原点）を採用。CAD原点と一致しており変換が最も単純。
- **データモデル**: Python標準 `dataclasses` を使用（Pydantic等の外部依存なし）。
- **AI設計**: `NullAiEngine` をデフォルトとし、外部APIへのデータ送信は行わない設計。
- **Geometry Engine**: Shapelyを直接使わず `IGeometryEngine` を通じて利用。将来的に交換可能。

---

### 未実装・Phase 1以降で実施すべき内容

| 機能 | フェーズ |
|------|---------|
| DXFファイルの実際のパース (`ezdxf` 利用) | Phase 1 |
---

## Phase 1 — DXF図面Viewerの実装とEXE化

**実施日**: 2026-09-14  
**所要時間**: 約 75 分  
**担当**: Antigravity AI + ユーザー承認

---

### 実施内容

1. **テストデータ生成スクリプトの作成** (`scripts/generate_sample_dxfs.py`)
   - `ezdxf` を用いて、単一矩形、複合矩形（複数部屋）、直線＋円弧（壁開口・建具想定）、テキスト＋MTEXT（部屋名想定）の4パターンのテストDXFを自動生成。
   - `close()` メソッドの誤用による AttributeError を、フラグ属性 `is_closed = True` およびポリゴン終点自動結合に修正。

2. **DXFパーサーの実装と堅牢化** (`core/parser/dxf_parser.py`)
   - DXFエンティティ（LINE, LWPOLYLINE, POLYLINE, ARC, CIRCLE, TEXT, MTEXT）から内部データモデル（`LineElement`, `PolylineElement`, `ArcElement`, `CircleElement`, `TextElement`）への完全な変換ロジックを実装。
   - MTEXTの取得において、バージョン差異や属性の有無に応じたフォールバック機構（`plain_text()`, `plain_mtext()`, `dxf.text`）を実装し、どのようなDXFでもパースが失敗しないよう堅牢化。
   - レイヤー情報（レイヤー名、色、表示状態）の抽出およびDXFカラーインデックス（ACI）のRGB変換に対応。

3. **DXFビューア・GUI連携の実装** (`core/drawing_viewer/`, `ui/main_window.py`)
   - Qt Graphics View フレームワークを用いた描画シーン（`DrawingScene`）とビュー（`DrawingView`）の統合。
   - マウスホイールによるスムーズなズーム（カーソル位置中心）、中ボタンドラッグによるパン操作、全体表示（Fit-to-View）機能。
   - 大きな図面でもUIがフリーズしないよう、`QThread`（`DxfLoadWorker`）を用いた非同期読み込みおよびプログレスバー・ステータスバー連動。
   - ファイル読み込み失敗時にアプリがクラッシュせず、原因と詳細をユーザー向けダイアログで表示するエラーハンドリング。

4. **ユニットテストの拡充と全件合格**
   - 既存のスタブテストを実パース検証へ更新し、`tests/test_dxf_parser.py` を追加。
   - 全30件のテストがパス（`30 passed`）。

5. **Windows向けEXE化とセキュリティソフト誤検知回避** (`scripts/build_exe.py`)
   - PyInstaller 6.x を使用したスタンドアロンEXE化スクリプトの作成。
   - **発生した課題と修正経緯**:
     - *パス内絵文字 (`💻️`)*: Windows API/CランタイムがANSI変換できず `[Errno 22]` が発生したため、ビルドワークディレクトリをテンポラリ領域（英数字パス）に分離してビルド完了後にプロジェクト内 `dist/` へ転送する方式を採用。
     - *Windows mmap ロック*: pefile の mmap による排他エラーを回避するため、インメモリバッファ読み込みに安全化。
     - *ノートン 360 (Norton 360) による誤検知隔離*: ノートン 360 の SONAR（振る舞い検知）が、未署名EXE（PyInstallerのGUIブートローダ `runw.exe`）をマルウェアと誤検知して即時隔離・削除（`FileNotFoundError`）することが判明。
       - **対策**: ブートローダを誤検知されない標準ブートローダ（コンソールモード）とし、PyInstallerの `--hide-console=hide-early` オプションと `main.py` 冒頭の Windows API `ShowWindow(SW_HIDE)` を組み合わせて、起動時にコンソールウィンドウを即座に非表示化。NortonにブロックされずにGUIウィンドウのみがすっきりと起動するスタンドアロンEXEのビルドに成功。

---

### 決定事項・設計上の判断

- **CAD再現ではなく図面確認優先**: 線幅や複雑なハッチング・寸法線はPhase 1では過剰装飾とせず、建築要素（線・ポリライン・円弧・円・文字）を軽快かつ明瞭に可視化することを最優先とした。
- **セキュリティソフト親和性**: 現場PC（Norton等のセキュリティソフト導入環境）でも誤検知で削除されない起動構造を採用。

---

### Phase 1 完了時点での未実装・Phase 2以降の予定

| 機能 | フェーズ |
|------|---------|
| レイヤー表示切替・ツリービュー連携 | Phase 2 |
| 部屋領域のポリゴン化・面積算定 | Phase 3-5 |
| 壁線の自動分類・壁芯抽出ロジック | Phase 4 |
| PDF/画像のパース実装 | Phase 6 |
| OCRエンジンの実装 (Tesseract等) | Phase 7 |
| AI補助機能の実装 | Phase 8 |
| 図面差分比較機能 | Phase 9 |

---

### 累計要した時間

| フェーズ | 実施日 | 所要時間 |
|---------|--------|---------|
| Phase 0 (基盤設計・共通モデル) | 2026-08-31 | 約 60 分 |
| Phase 1 (DXF図面Viewer・EXE化) | 2026-09-14 | 約 75 分 |
| **合計** | | **約 135 分 (2時間15分)** |


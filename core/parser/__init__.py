"""
core.parser
CAD (DXF)、PDF、画像などの異なるファイル形式から図面情報を抽出するパーサーを提供します。
"""

from .interface import IDrawingParser
from .dxf_parser import DxfParser
from .pdf_parser import PdfParser
from .image_parser import ImageParser

__all__ = [
    "IDrawingParser",
    "DxfParser",
    "PdfParser",
    "ImageParser",
]

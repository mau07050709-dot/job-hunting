"""Print available local Windows OCR languages; does not capture the screen."""
import sys
if sys.platform != "win32":
    raise SystemExit("Windows OCR is available only on Windows.")
from winrt.windows.media.ocr import OcrEngine
print("Available OCR languages:", ", ".join(x.language_tag for x in OcrEngine.available_recognizer_languages))

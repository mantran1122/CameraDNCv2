"""Lớp giao diện Streamlit của ứng dụng.

Các màn hình và thành phần hiển thị nằm trong package này. Business logic
tiếp tục ở ``app.streamlit_app`` và được truyền vào UI qua ``UiApi``.
"""

from . import dashboard

__all__ = ["dashboard"]

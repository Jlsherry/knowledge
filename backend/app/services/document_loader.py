"""文档解析服务：支持 PDF、Word、TXT 格式。"""

from pathlib import Path

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_core.documents import Document


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def get_file_type(filename: str) -> str:
    """根据文件扩展名返回类型标识。"""
    ext = Path(filename).suffix.lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}
    if ext not in mapping:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 pdf/docx/txt")
    return mapping[ext]


def _validate_docx(file_path: Path) -> None:
    """
    校验是否为真正的 .docx 文件（本质是 ZIP，文件头为 PK）。

    旧版 Word .doc（OLE 格式，文件头 D0 CF 11 E0）仅改扩展名无法解析。
    """
    head = file_path.read_bytes()[:4]
    if head[:2] == b"PK":
        return
    if head == b"\xd0\xcf\x11\xe0":
        raise ValueError(
            "该文件实际为旧版 Word (.doc) 格式，不是 .docx。"
            "请用 Word 或 WPS 打开后，选择「另存为」→「Word 文档 (*.docx)」再上传。"
        )
    raise ValueError("文件不是有效的 .docx 格式，可能已损坏或格式不正确")


def _load_docx(file_path: Path) -> list[Document]:
    """加载 .docx 文件，解析前校验文件格式。"""
    _validate_docx(file_path)
    loader = Docx2txtLoader(str(file_path))
    return loader.load()


def _load_txt(file_path: Path) -> list[Document]:
    """
    加载 TXT 文件，依次尝试 utf-8 / gbk 等常见编码。

    避免依赖 chardet，兼容中文 Windows 环境下保存的文本。
    """
    raw = file_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030"):
        try:
            text = raw.decode(encoding)
            return [Document(page_content=text, metadata={"source": str(file_path)})]
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 TXT 文件编码，请另存为 UTF-8 格式后重试")


def load_document(file_path: Path, file_type: str) -> list[Document]:
    """
    按文件类型选择对应 Loader 解析文档为 LangChain Document 列表。

    每个 Document 包含 page_content 和 metadata（如 source、page）。
    """
    path_str = str(file_path)

    if file_type == "pdf":
        loader = PyPDFLoader(path_str)
    elif file_type == "docx":
        return _load_docx(file_path)
    elif file_type == "txt":
        return _load_txt(file_path)
    else:
        raise ValueError(f"未知文件类型: {file_type}")

    return loader.load()

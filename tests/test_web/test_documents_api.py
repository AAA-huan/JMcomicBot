"""文档接口目录、正文、认证与路径约束测试。"""

from src.web.api.document_routes import create_document_router
from tests.test_web.support import create_client_for, setup_and_login


def test_documents_list_nested_markdown_and_reject_escape(
    db_manager, tmp_path, monkeypatch
):
    """可阅读子目录文档，不可访问非 Markdown 或 docs 外的文件。"""
    docs = tmp_path / "docs"
    (docs / "deployment").mkdir(parents=True)
    (docs / "guide.md").write_text("# 使用指南\n正文", encoding="utf-8")
    (docs / "deployment/linux.md").write_text(
        "# Linux 部署\n安装步骤", encoding="utf-8"
    )
    (docs / "private.txt").write_text("非文档", encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("机密", encoding="utf-8")
    (docs / "escape.md").symlink_to(secret)
    # 在应用装配时注入临时文档目录，保留真实认证、中间件和路由顺序。
    monkeypatch.setattr(
        "src.web.api.router.create_document_router",
        lambda authenticate, _root: create_document_router(authenticate, docs),
    )
    client, _context = create_client_for(db_manager)
    with client:
        assert client.get("/api/v1/documents").status_code == 401
        setup_and_login(client)
        response = client.get("/api/v1/documents")
        assert response.status_code == 200
        assert response.json() == [
            {"path": "deployment/linux.md", "title": "Linux 部署"},
            {"path": "guide.md", "title": "使用指南"},
        ]
        assert (
            client.get("/api/v1/documents/deployment/linux.md").json()["content"]
            == "# Linux 部署\n安装步骤"
        )
        for path in ("escape.md", "private.txt", "%2e%2e%2fsecret.md", "missing.md"):
            response = client.get(f"/api/v1/documents/{path}")
            assert response.status_code == 404
            assert "机密" not in response.text

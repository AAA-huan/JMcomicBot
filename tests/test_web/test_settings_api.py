"""配置页 option.yml 网页编辑接口与新配置项测试。"""

from pathlib import Path

from tests.test_web.support import (
    PASSWORD,
    create_client_for,
    csrf_headers,
    setup_and_login,
)


def _make_client(db_manager, config_dict=None):
    """构造测试客户端（option_file_service 已由 build_web_context 注入）。"""
    client, _context = create_client_for(db_manager)
    return client


def test_option_file_get_returns_empty_when_missing(db_manager) -> None:
    """文件不存在时 GET 返回空串。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        response = client.get("/api/v1/settings/option-file")
        assert response.status_code == 200
        assert response.json() == {"content": ""}


def test_option_file_put_creates_and_returns_content(db_manager) -> None:
    """PUT 保存合法 YAML 后返回内容，文件落盘。"""
    client = _make_client(db_manager)
    content = "download:\n  image:\n    suffix: .jpg\n"
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        response = client.put(
            "/api/v1/settings/option-file",
            json={"content": content},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["updated"] is True
        assert response.json()["content"] == content

    # 文件应落在 build_web_context 构造的 download_root 下（与 option_file_service 路径一致）
    root = Path(db_manager.db_dir).parent
    option_path = root / "option.yml"
    assert option_path.exists()
    assert option_path.read_text(encoding="utf-8") == content


def test_option_file_put_rejects_non_dict_yaml(db_manager) -> None:
    """顶层非字典返回 400 OPTION_FILE_INVALID。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        response = client.put(
            "/api/v1/settings/option-file",
            json={"content": "- a\n- b\n"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "OPTION_FILE_INVALID"
        assert "顶层必须是字典" in response.json()["message"]


def test_option_file_put_rejects_invalid_yaml(db_manager) -> None:
    """非法 YAML 返回 400。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        response = client.put(
            "/api/v1/settings/option-file",
            json={"content": "not: {valid\n"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "OPTION_FILE_INVALID"


def test_option_file_get_requires_auth(db_manager) -> None:
    """未登录访问 option-file 返回 401。"""
    client = _make_client(db_manager)
    with client:
        response = client.get("/api/v1/settings/option-file")
        assert response.status_code == 401


def test_new_settings_db_echo_and_webui_dev_origins_listed(db_manager) -> None:
    """DB_ECHO 与 WEBUI_DEV_ORIGINS 应出现在配置列表。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        listing = client.get("/api/v1/settings")
        keys = {item["key"] for item in listing.json()["items"]}
        assert "DB_ECHO" in keys
        assert "WEBUI_DEV_ORIGINS" in keys

        db_echo = next(
            item for item in listing.json()["items"] if item["key"] == "DB_ECHO"
        )
        assert db_echo["value_type"] == "bool"
        assert db_echo["group"] == "数据库"
        assert db_echo["effect"] == "restart"


def test_webui_dev_origins_accepts_empty_and_valid(db_manager) -> None:
    """WEBUI_DEV_ORIGINS 允许空串与合法来源。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        empty = client.patch(
            "/api/v1/settings/WEBUI_DEV_ORIGINS",
            json={"value": ""},
            headers=headers,
        )
        assert empty.status_code == 200
        assert empty.json()["value"] == ""

        valid = client.patch(
            "/api/v1/settings/WEBUI_DEV_ORIGINS",
            json={"value": "http://127.0.0.1:5173,https://localhost:5173"},
            headers=headers,
        )
        assert valid.status_code == 200


def test_webui_dev_origins_rejects_invalid_origin(db_manager) -> None:
    """非法来源返回 400。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        response = client.patch(
            "/api/v1/settings/WEBUI_DEV_ORIGINS",
            json={"value": "ftp://bad-origin,http://good:5173"},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SETTING_INVALID_VALUE"
        assert "ftp://bad-origin" in response.json()["message"]

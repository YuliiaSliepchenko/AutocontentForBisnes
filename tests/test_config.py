from backend.app.config import Settings


def test_dotenv_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ('HOST', 'PORT', 'AUTOCONTENT_DATA_DIR', 'AUTOCONTENT_PROVIDER'):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / '.env').write_text('HOST=127.0.0.1\nPORT=8123\nAUTOCONTENT_DATA_DIR=local-data\nAUTOCONTENT_PROVIDER=mock\n', encoding='utf-8')
    settings = Settings()
    assert settings.port == 8123
    assert str(settings.autocontent_data_dir) == 'local-data'
    monkeypatch.setenv('PORT', '8124')
    assert Settings().port == 8124

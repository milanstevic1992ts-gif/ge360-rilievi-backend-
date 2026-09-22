from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_control_contains_integrated_settings_ui():
    html = (ROOT / "control" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "control" / "control.js").read_text(encoding="utf-8")

    assert 'data-view="settings"' in html
    assert 'id="view-settings"' in html
    assert 'id="bridgeSettingsDiagnosticsBtn"' in html
    assert 'id="settingsPairBtn"' in html
    assert 'id="settingsRotateKeyBtn"' in html
    assert 'id="settingsDevices"' in html

    assert "settingsApi('/setup/status')" in js
    assert "settingsApi('/bridge/status')" in js
    assert "settingsApi('/bridge/devices')" in js
    assert "settingsApi('/bridge/diagnostics')" in js
    assert "settingsApi('/bridge/restart'" in js
    assert "settingsApi('/setup/api-key'" in js
    assert "localStorage.setItem('ge360ControlKey',state.key)" in js


def test_legacy_setup_routes_to_control_settings():
    html = (ROOT / "setup" / "index.html").read_text(encoding="utf-8")
    target = "/control/?view=settings&bootstrap=1"
    assert target in html
    assert "GE360 · Impostazioni" in html


def test_control_settings_keep_linux_recovery_commands_visible():
    html = (ROOT / "control" / "index.html").read_text(encoding="utf-8")
    assert "recover-linux-install.sh" in html
    assert "install-direct-bridge.sh" in html
    assert "ge360-rilievi-status" in html
    assert "non esporre TCP 9888" in html


def test_documents_view_contains_local_archive_and_backup_status():
    html = (ROOT / "control" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "control" / "control.js").read_text(encoding="utf-8")

    assert 'id="documentsArchiveGrid"' in html
    assert 'id="syncDocumentsArchiveBtn"' in html
    assert 'id="configBackupDetails"' in html
    assert 'id="configRestoreCommand"' in html

    assert "/control/documents-archive" in js
    assert "/control/config-backups" in js
    assert "renderDocumentsArchive" in js
    assert "renderConfigBackups" in js
    assert "sudo ge360-config-restore latest" in js

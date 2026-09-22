from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_direct_bridge_installer_repairs_service_permissions_and_environment():
    script = (ROOT / "scripts" / "install-direct-bridge.sh").read_text(encoding="utf-8")
    assert "acl" in script
    assert 'setfacl -m "g:$GROUP_NAME:--x" "$STATE_PARENT"' in script
    assert 'setfacl -R -m "g:$GROUP_NAME:rwX" "$STATE_DIR" "$CONFIG_DIR"' in script
    assert "EnvironmentFile=-$ENV_FILE" in script
    assert "SupplementaryGroups=$GROUP_NAME" in script
    assert "ReadWritePaths=$CONFIG_DIR $STATE_DIR" in script
    assert "--host 0.0.0.0 --port 9888" in script


def test_debian_install_verifies_control_and_refreshes_existing_bridge():
    script = (ROOT / "scripts" / "install-debian.sh").read_text(encoding="utf-8")
    assert "verify-control-assets.py" in script
    assert "/usr/local/sbin/ge360-rilievi-update" in script
    assert "Existing GE360 Direct Bridge detected" in script
    assert "install-direct-bridge.sh" in script


def test_updater_does_not_require_deployment_directory_to_be_git_checkout():
    script = (ROOT / "scripts" / "update-debian.sh").read_text(encoding="utf-8")
    assert "api.github.com/repos" in script
    assert "archive/" in script
    assert "install-debian.sh" in script
    assert ".ge360-deploy-sha" in script
    assert "git pull" not in script

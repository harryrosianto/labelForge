import pytest

from lfcapture.config import ConfigError, load_config, read_env_file
from tests.helpers import BASE_ENV, make_config


def test_defaults_and_loopback_tls(tmp_path):
    cfg = make_config(tmp_path)
    assert cfg.insecure_tls is True  # loopback tanpa CA: verifikasi boleh dilewati
    assert cfg.classes[0] == "person" and cfg.person_class == "person"
    assert cfg.camera_ids == ()
    assert "rahasia" not in repr(cfg)  # password tidak ikut tercetak di log


def test_remote_host_requires_ca_or_explicit_insecure(tmp_path):
    with pytest.raises(ConfigError, match="SG_CA_FILE"):
        make_config(tmp_path, SG_URL="https://192.168.110.243:8080")
    assert make_config(tmp_path, SG_URL="https://192.168.110.243:8080", SG_INSECURE_TLS="1").insecure_tls
    cfg = make_config(tmp_path, SG_URL="https://192.168.110.243:8080", SG_CA_FILE="cert.pem")
    assert cfg.insecure_tls is False and cfg.ca_file == "cert.pem"


def test_validation(tmp_path):
    with pytest.raises(ConfigError, match="wajib"):
        load_config({"SG_USERNAME": "x", "CAPTURE_DIR": str(tmp_path)})
    with pytest.raises(ConfigError, match="angka"):
        make_config(tmp_path, CAPTURE_INTERVAL_S="sepuluh")
    with pytest.raises(ConfigError, match="UNCERTAIN"):
        make_config(tmp_path, CAPTURE_UNCERTAIN_LOW="0.7", CAPTURE_UNCERTAIN_HIGH="0.6")
    with pytest.raises(ConfigError, match="PERSON_CLASS"):
        make_config(tmp_path, CAPTURE_CLASSES="Helmet,Mask")
    cfg = make_config(tmp_path, CAPTURE_CLASSES="Helmet, Mask", CAPTURE_PERSON_CLASS="",
                      CAPTURE_CAMERAS="3, 5")  # fmt: skip
    assert cfg.classes == ("Helmet", "Mask") and cfg.person_class is None and cfg.camera_ids == (3, 5)


def test_env_file_and_password_file(tmp_path):
    (tmp_path / "pw").write_text("dari-file\n")
    env_file = tmp_path / "capture.env"
    env_file.write_text(
        "# komentar\n"
        "SG_USERNAME=perekam\n"
        f'SG_PASSWORD_FILE="{(tmp_path / "pw").as_posix()}"\n'
        f"CAPTURE_DIR='{tmp_path.as_posix()}'\n"
        "CAPTURE_CLASSES=person,Helmet,Safety Vest\n"
    )
    env = read_env_file(env_file)
    assert env["CAPTURE_CLASSES"] == "person,Helmet,Safety Vest"
    cfg = load_config(env)
    assert cfg.password == "dari-file" and cfg.classes[-1] == "Safety Vest"
    assert BASE_ENV["SG_URL"] == cfg.sg_url


def test_aspect_setting(tmp_path):
    from lfcapture.config import parse_aspect

    assert make_config(tmp_path).aspect == "auto"
    assert make_config(tmp_path, CAPTURE_ASPECT="16:9").aspect == "16:9"
    assert make_config(tmp_path, CAPTURE_ASPECT="OFF").aspect == "off"
    with pytest.raises(ConfigError, match="CAPTURE_ASPECT"):
        make_config(tmp_path, CAPTURE_ASPECT="lebar")
    assert parse_aspect("1280x720") == (1280, 720) and parse_aspect("4:3") == (4, 3)
    assert parse_aspect("0x720") is None and parse_aspect("") is None


def test_usb_uuid(tmp_path):
    assert make_config(tmp_path).usb_uuid is None
    assert make_config(tmp_path, CAPTURE_USB_UUID="D468-AC1E").usb_uuid == "D468-AC1E"
    for bad in ("../sda1", "D468AC1E", "D468-AC1E; rm"):
        with pytest.raises(ConfigError, match="CAPTURE_USB_UUID"):
            make_config(tmp_path, CAPTURE_USB_UUID=bad)

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("HARMELUNE_TAURI_E2E") != "1",
    reason="Set HARMELUNE_TAURI_E2E=1 to launch and drive the native Tauri app.",
)


def _write_wav(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    return path.read_bytes()


def _wait_for_port(host: str, port: int, process: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"tauri-driver exited early with code {process.returncode}")
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("tauri-driver did not open its WebDriver port in time.")


def test_native_tauri_user_journey(tmp_path: Path):
    """Launch the actual Windows app and drive the core read-only user journey."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as conditions
    from selenium.webdriver.support.ui import WebDriverWait

    app_path = Path(os.environ["HARMELUNE_TAURI_APP"]).resolve()
    assert app_path.is_file(), f"Built Tauri application not found: {app_path}"

    os.environ["APPDATA"] = str(tmp_path / "isolated-app-data")
    library_a = tmp_path / "Library A Ω"
    library_b = tmp_path / "Library B"
    source_track = library_a / "Album" / "Synthetic track.wav"
    original_bytes = _write_wav(source_track)
    library_b.mkdir(parents=True)

    screenshots = Path(os.environ.get("HARMELUNE_E2E_ARTIFACTS", "artifacts/tauri-e2e"))
    screenshots.mkdir(parents=True, exist_ok=True)
    driver_process = subprocess.Popen(
        ["tauri-driver", "--port", "4444"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    driver = None
    try:
        _wait_for_port("127.0.0.1", 4444, driver_process)
        options = webdriver.ChromeOptions()
        options.set_capability("browserName", "wry")
        options.set_capability("tauri:options", {"application": str(app_path)})
        driver = webdriver.Remote(
            command_executor="http://127.0.0.1:4444/",
            options=options,
        )
        driver.set_page_load_timeout(30)
        wait = WebDriverWait(driver, 30)

        # The real desktop shell must render its complete primary navigation.
        for label in (
            "Library", "Compare", "Review & preview", "Mirror",
            "Backups & recovery", "Sync history", "Library health",
        ):
            wait.until(conditions.visibility_of_element_located(
                (By.XPATH, f"//nav[@aria-label='Main navigation']//button[.//span[normalize-space()='{label}']]")
            ))

        # Enter fixture paths through the same accessible controls a user uses.
        wait.until(conditions.visibility_of_element_located((By.ID, "library-a-path"))).send_keys(str(library_a))
        driver.find_element(By.ID, "library-b-path").send_keys(str(library_b))
        driver.find_element(By.XPATH, "//button[normalize-space()='Scan & compare libraries']").click()

        wait.until(conditions.visibility_of_element_located(
            (By.XPATH, "//h2[normalize-space()='Comparison snapshot']")
        ))
        wait.until(conditions.text_to_be_present_in_element(
            (By.CSS_SELECTOR, ".comparison-table-wrap"), "Synthetic track"
        ))
        assert source_track.read_bytes() == original_bytes
        assert list(library_b.rglob("*")) == []

        # The Health page must use a real scan result from the Python sidecar.
        driver.find_element(By.XPATH, "//nav//button[.//span[normalize-space()='Library health']]").click()
        wait.until(conditions.visibility_of_element_located(
            (By.XPATH, "//h2[normalize-space()='Library health']")
        ))
        health_values = [item.text for item in driver.find_elements(By.CSS_SELECTOR, ".metric-card strong")]
        assert "1" in health_values, f"Expected one scanned track in health metrics: {health_values}"

        # Persistent History and Recovery empty states are reachable and readable.
        driver.find_element(By.XPATH, "//nav//button[.//span[normalize-space()='Sync history']]").click()
        wait.until(conditions.text_to_be_present_in_element(
            (By.CSS_SELECTOR, ".page-content"), "Persistent local history"
        ))
        driver.find_element(By.XPATH, "//nav//button[.//span[normalize-space()='Backups & recovery']]").click()
        wait.until(conditions.visibility_of_element_located((By.ID, "restore-backup-path")))
        assert "Restore" in driver.find_element(By.CSS_SELECTOR, ".page-content").text

        # Resize the real desktop window and verify that the primary workspace
        # remains reachable without a document-level horizontal overflow.
        driver.set_window_size(1000, 760)
        overflow = driver.execute_script(
            "return document.documentElement.scrollWidth > window.innerWidth + 2"
        )
        assert overflow is False, "Desktop workspace overflowed horizontally at 1000x760."

        driver.save_screenshot(str(screenshots / "tauri-user-journey.png"))
        assert source_track.read_bytes() == original_bytes
        assert list(library_b.rglob("*")) == []
    except Exception:
        if driver is not None:
            driver.save_screenshot(str(screenshots / "tauri-user-journey-failure.png"))
        raise
    finally:
        if driver is not None:
            driver.quit()
        driver_process.terminate()
        try:
            driver_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            driver_process.kill()
            driver_process.wait(timeout=5)

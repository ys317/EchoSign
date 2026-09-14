"""Read the Windows system location on demand without an external lookup service."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from echosign.processes import hidden_subprocess_options


DEFAULT_LAT = 30.314732
DEFAULT_LNG = 120.343727


@dataclass(frozen=True)
class Location:
    lat: float
    lng: float
    accuracy_m: float | None = None


class LocationError(Exception):
    """A location request failed; the message can be shown directly in the UI."""


# System.Device uses the Windows location provider and its privacy settings. It
# does not contact a separate IP lookup or geocoding service. SuppressPermissionPrompt
# keeps this background helper silent; the error points to Windows settings when
# consent is missing. The Python timeout also covers PowerShell startup or hangs.
_POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$watcher = $null
$result = @{ status = 'failed' }
try {
    Add-Type -AssemblyName System.Device
    $watcher = New-Object -TypeName System.Device.Location.GeoCoordinateWatcher -ArgumentList ([System.Device.Location.GeoPositionAccuracy]::High)
    $watcher.Start($true)
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        if ($watcher.Permission -eq [System.Device.Location.GeoPositionPermission]::Denied) {
            $result = @{ status = 'denied' }
            break
        }
        if ($watcher.Status -eq [System.Device.Location.GeoPositionStatus]::Disabled) {
            $result = @{ status = 'disabled' }
            break
        }
        $coordinate = $watcher.Position.Location
        if (-not $coordinate.IsUnknown) {
            $accuracy = $coordinate.HorizontalAccuracy
            if ([double]::IsNaN($accuracy) -or [double]::IsInfinity($accuracy) -or $accuracy -lt 0) {
                $accuracy = $null
            }
            $result = @{
                status = 'ok'
                lat = $coordinate.Latitude
                lng = $coordinate.Longitude
                accuracy_m = $accuracy
            }
            break
        }
        if ($timer.Elapsed.TotalMilliseconds -ge __TIMEOUT_MS__) {
            $status = 'timeout'
            if ($watcher.Status -eq [System.Device.Location.GeoPositionStatus]::NoData) {
                $status = 'unavailable'
            }
            $result = @{ status = $status }
            break
        }
        Start-Sleep -Milliseconds 100
    }
}
catch [System.UnauthorizedAccessException] {
    $result = @{ status = 'denied' }
}
catch {
    $result = @{ status = 'failed' }
}
finally {
    if ($null -ne $watcher) { $watcher.Dispose() }
}
[Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
"""

_ERROR_MESSAGES = {
    "denied": "Windows 拒绝了定位权限。请在 Windows 设置的“隐私和安全性 → 位置”中开启定位服务，并允许桌面应用访问位置；也可以手动填写经纬度。",
    "disabled": "Windows 定位服务已关闭或不可用。请在 Windows 设置的“隐私和安全性 → 位置”中开启定位服务；也可以手动填写经纬度。",
    "timeout": "获取本机位置超时。请检查 Windows 定位服务后重试，或手动填写经纬度。",
    "unavailable": "Windows 暂时没有可用的位置数据。请检查定位服务和设备的定位能力，或手动填写经纬度。",
    "failed": "无法调用 Windows 系统定位。请检查定位服务后重试，或手动填写经纬度。",
}


def get_current_location(timeout_s: float = 20.0) -> Location:
    """Get coordinates supplied by Windows; never substitute a default location.

    Call from a worker thread because acquisition may take up to ``timeout_s``.
    No location is requested merely by importing this module.
    """
    if sys.platform != "win32":
        raise LocationError("当前系统暂不支持自动获取本机位置，请手动填写经纬度。")
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError, OverflowError):
        raise LocationError("定位超时必须是大于 0 的有限秒数。") from None
    if isinstance(timeout_s, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise LocationError("定位超时必须是大于 0 的有限秒数。")

    # Give the helper a little time to serialize/dispose before the overall
    # timeout, which is enforced by subprocess.run even if Windows gets stuck.
    wait_ms = max(1, int(max(0.0, timeout - 1.0) * 1000))
    script = _POWERSHELL_SCRIPT.replace("__TIMEOUT_MS__", str(wait_ms))
    powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
                  / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    try:
        completed = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-Command", script],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            **hidden_subprocess_options())
    except subprocess.TimeoutExpired:
        raise LocationError(_ERROR_MESSAGES["timeout"]) from None
    except FileNotFoundError:
        raise LocationError("未找到 Windows PowerShell，无法获取本机位置，请手动填写经纬度。") from None
    except OSError:
        raise LocationError(_ERROR_MESSAGES["failed"]) from None

    if completed.returncode != 0:
        raise LocationError(_ERROR_MESSAGES["failed"])
    try:
        result = json.loads(completed.stdout.lstrip("\ufeff").strip())
    except (TypeError, ValueError):
        raise LocationError("Windows 定位返回了无法解析的结果，请重试或手动填写经纬度。") from None
    if not isinstance(result, dict):
        raise LocationError("Windows 定位返回了无法解析的结果，请重试或手动填写经纬度。")
    status = result.get("status")
    if status != "ok":
        if not isinstance(status, str):
            status = "failed"
        raise LocationError(_ERROR_MESSAGES.get(status, _ERROR_MESSAGES["failed"]))

    lat, lng = result.get("lat"), result.get("lng")
    if (not _finite_number(lat) or not _finite_number(lng)
            or not -90 <= lat <= 90 or not -180 <= lng <= 180):
        raise LocationError("Windows 定位返回了无效经纬度，请重试或手动填写经纬度。")
    accuracy = result.get("accuracy_m")
    if not _finite_number(accuracy) or accuracy < 0:
        accuracy = None
    return Location(float(lat), float(lng), float(accuracy) if accuracy is not None else None)


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

"""Resolve one current HDU live stream and keep its login separate from sign-in."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

import requests
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from echosign.runtime import application_root, configure_browser_runtime


_SITE_HOSTS = frozenset(("course.hdu.edu.cn",
                        "https-course-hdu-edu-cn-443.webvpn.hdu.edu.cn"))
_SSO_HOSTS = frozenset(("sso.hdu.edu.cn", "cas.hdu.edu.cn",
                       "https-sso-hdu-edu-cn-443.webvpn.hdu.edu.cn",
                       "https-cas-hdu-edu-cn-443.webvpn.hdu.edu.cn"))
_API = "/jy-application-resourcemanage"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")
_LOGIN_TIMEOUT_SECONDS = 180.0
_BEIJING = dt.timezone(dt.timedelta(hours=8))
_COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_\x60|~0-9A-Za-z]+\Z")
_UNSUPPORTED = "当前直播格式暂不支持，请使用电脑声音模式。"


class LiveError(RuntimeError):
    """A user-readable error that never contains a signed URL or credential."""

    retryable = False


class LiveTransientError(LiveError):
    """A temporary failure that may be retried for this same course only."""

    retryable = True


class LiveEnded(LiveError):
    """The requested live class has ended; do not retry or select another one."""


class LiveLoginRequired(LiveError):
    """The user needs to complete the separate live-platform login."""


@dataclass
class LiveStream:
    url: str = field(repr=False)
    headers: dict = field(repr=False)
    title: str = "直播音频"


def _plain(value: object) -> bool:
    return (isinstance(value, str)
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _url(value: object):
    if not _plain(value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            return None
        parsed.port
        return parsed
    except ValueError:
        return None


def parse_live_page(page_url: str) -> tuple[str, str]:
    """Return the allowed origin and one course ID; reject replay/share routes."""
    page = _url(page_url)
    if (page is None or page.scheme != "https" or page.hostname not in _SITE_HOSTS
            or page.port not in (None, 443)):
        raise LiveError("请填写杭电课堂直播页面的网址。")
    route = _url(page.fragment) if page.fragment else page
    if route is None:
        raise LiveError("请使用正在上课的直播链接；该链接不是有效的单节直播页面。")
    query = parse_qs(route.query, keep_blank_values=True)
    ids = query.get("courseId", [])
    if (route.path not in ("/play-center", "/play-live")
            or query.get("target") != ["live"] or len(ids) != 1
            or re.fullmatch(r"[0-9]{1,20}", ids[0]) is None or int(ids[0]) <= 0):
        raise LiveError("请使用正在上课的直播链接；该链接不是有效的单节直播页面。")
    return "https://" + page.hostname, str(int(ids[0]))


def _domain_matches(domain: str, host: str) -> bool:
    base = domain.lstrip(".").lower()
    return host == base or (domain.startswith(".") and host.endswith("." + base))


def _cookies_for_origin(raw: object, origin: str) -> list[dict]:
    host = urlsplit(origin).hostname
    result = []
    for cookie in raw if isinstance(raw, list) else []:
        if not isinstance(cookie, dict):
            continue
        name, value = cookie.get("name"), cookie.get("value")
        domain, path = cookie.get("domain"), cookie.get("path", "/")
        if (not isinstance(name, str) or not _COOKIE_NAME.fullmatch(name)
                or not _plain(value) or ";" in value or not _plain(domain)
                or not (domain.lstrip(".") == "hdu.edu.cn"
                        or domain.lstrip(".").endswith(".hdu.edu.cn"))
                or not _domain_matches(domain, host)
                or not _plain(path) or not path.startswith("/")):
            continue
        expiry = cookie.get("expires")
        if expiry not in (None, -1):
            if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
                    or not math.isfinite(expiry) or expiry <= time.time()):
                continue
        result.append({"name": name, "value": value, "domain": domain,
                       "path": path, "secure": bool(cookie.get("secure", False)),
                       "expires": expiry})
    return result


def _timestamp(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, str) and not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
            when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            result = when.replace(tzinfo=_BEIJING).timestamp() if when.tzinfo is None else when.timestamp()
        else:
            result = float(value)
            if abs(result) >= 100_000_000_000:
                result /= 1000
        return result if math.isfinite(result) and 0 <= result < 32_503_680_000 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _status(value: object, expected: int) -> bool:
    return not isinstance(value, bool) and value in (expected, str(expected))


def _transient_status(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, str) and re.fullmatch(r"[0-9]{3}", value):
        value = int(value)
    return isinstance(value, int) and (value in (408, 429) or 500 <= value <= 599)


class LiveClient:
    """Only GET the live-info endpoint; never send viewing records or heartbeats."""

    parse_live_page = staticmethod(parse_live_page)

    def __init__(self, page_url: str, config: dict | None = None):
        self.origin, self.course_id = parse_live_page(page_url)
        auth = None
        try:
            auth = json.loads((application_root() / "live_session.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
        if not isinstance(auth, dict) or auth.get("origin") != self.origin:
            raise LiveLoginRequired("请先点击“登录直播”，完成本站登录。")
        self._cookies = _cookies_for_origin(auth.get("cookies"), self.origin)
        jwt = auth.get("jwt_token", "")
        if not _plain(jwt) or not jwt.isascii():
            raise LiveLoginRequired("直播登录资料无效，请重新点击“登录直播”。")
        if not self._cookies and not jwt:
            raise LiveLoginRequired("直播登录已失效，请重新点击“登录直播”。")
        self._session = requests.Session()
        # Do not implicitly load unrelated .netrc credentials. Retain the user's
        # proxy preference explicitly, without changing global network settings.
        self._session.trust_env = False
        options = (config or {}).get("browser") or {}
        if not options.get("bypass_proxy", False):
            self._session.proxies.update(requests.utils.get_environ_proxies(self.origin))
        self._session.headers.update({"User-Agent": _UA,
                                      "Accept": "application/json, text/plain, */*",
                                      "Referer": self.origin + "/"})
        if jwt:
            self._session.headers["jwt-token"] = jwt
        for cookie in self._cookies:
            self._session.cookies.set(
                cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"],
                secure=cookie["secure"],
                expires=int(cookie["expires"]) if cookie["expires"] not in (None, -1) else None)
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session.close()
            self._session.headers.pop("jwt-token", None)
            self._session.cookies.clear()
            self._cookies.clear()

    def _get_info(self) -> dict:
        response = None
        failure_type = LiveError
        failure_message = "无法连接课堂直播平台，请检查网络后重试。"
        try:
            response = self._session.get(
                self.origin + _API + "/v1/course_vod_videoinfos",
                params={"courseId": self.course_id, "playType": 2},
                timeout=(10, 15), allow_redirects=False)
        except requests.exceptions.SSLError:
            failure_message = "课堂直播平台的安全连接验证失败，请检查系统时间或联系平台。"
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            failure_type = LiveTransientError
        except (requests.RequestException, OSError, ValueError):
            pass
        if response is None:
            raise failure_type(failure_message)
        try:
            if response.status_code in (301, 302, 303, 307, 308, 401):
                raise LiveLoginRequired("直播登录已失效，请重新点击“登录直播”。")
            if response.status_code == 403:
                raise LiveError("当前账号无权观看这节直播。")
            if _transient_status(response.status_code):
                raise LiveTransientError("课堂直播平台暂时无法提供音频，请稍后重试。")
            if response.status_code != 200:
                raise LiveError("课堂直播平台暂时无法提供音频，请稍后重试。")
            payload = None
            try:
                payload = response.json()
            except (ValueError, TypeError):
                pass
            if not isinstance(payload, dict):
                raise LiveError("无法解析直播状态，请重新登录直播后重试。")
            return payload
        finally:
            response.close()

    def resolve(self) -> LiveStream:
        if self._closed:
            raise LiveError("直播连接已关闭，请重新开始监控。")
        payload = self._get_info()
        if _status(payload.get("status"), 401) or _status(payload.get("code"), 401):
            raise LiveLoginRequired("直播登录已失效，请重新点击“登录直播”。")
        if _status(payload.get("status"), 403) or _status(payload.get("code"), 403):
            raise LiveError("当前账号无权观看这节直播。")
        info = payload.get("data")
        if isinstance(info, dict) and _status(info.get("lvcrLiveStatus"), 0):
            raise LiveError("当前账号无权观看这节直播。")
        # The platform uses business status 501 for "live has not started";
        # it is not the same condition as an HTTP 501 server failure.
        if _status(payload.get("status"), 501):
            raise LiveError("这节直播尚未开始，请开播后再试。")
        if _transient_status(payload.get("status")) or _transient_status(payload.get("code")):
            raise LiveTransientError("课堂直播平台暂时无法提供音频，请稍后重试。")
        if (not _status(payload.get("status"), 200) or payload.get("ok") is False
                or not isinstance(info, dict)):
            raise LiveError("课堂直播平台未提供有效直播状态，请在网页确认这节课已开播。")
        if info.get("errorMsg"):
            raise LiveError("课堂直播平台未提供可播放的音频，请在网页确认直播状态。")
        if info.get("id") is not None and str(info["id"]) != self.course_id:
            raise LiveError("直播课程与链接不一致，请重新复制当前直播链接。")
        start, end = _timestamp(info.get("liveStartTime")), _timestamp(info.get("liveEndTime"))
        now = _timestamp(payload.get("timestamp"))
        now = time.time() if now is None else now
        if ((info.get("liveStartTime") not in (None, "") and start is None)
                or (info.get("liveEndTime") not in (None, "") and end is None)
                or (start is not None and end is not None and end <= start)):
            raise LiveError("无法确认当前直播时段，请在网页确认这节课正在直播。")
        if start is not None and now < start:
            raise LiveError("这节直播尚未开始，请开播后再试。")
        if end is not None and now >= end:
            raise LiveEnded("这节直播已经结束，请使用当前正在上课的直播链接。")
        views = info.get("courseDeviceViewDtoList")
        if not isinstance(views, list):
            raise LiveError("直播平台未返回设备信息，请在网页确认直播状态。")
        if not views:
            raise LiveTransientError("这节直播暂时没有音频，请稍后重试。")
        for view in views:
            if not isinstance(view, dict):
                continue
            media = _url(view.get("chanNameMainPlayUrl"))
            if (media is None or media.scheme not in ("http", "https") or not media.hostname
                    or media.fragment or Path(media.path).suffix.lower() not in ("", ".flv")):
                continue
            token = view.get("mainTokenStr", "")
            if token is None:
                token = ""
            if not _plain(token):
                continue
            query = media.query
            if token:
                parts = [part for part in query.split("&") if part
                         and unquote(part.split("=", 1)[0]) != "account_token"]
                parts.append("account_token=" + quote(token, safe=""))
                query = "&".join(parts)
            url = urlunsplit((media.scheme, media.netloc, media.path, query, ""))
            # The official FLV client authenticates with account_token. Passing
            # Cookie/JWT as raw FFmpeg headers would also forward them on redirects.
            headers = {"User-Agent": _UA, "Referer": self.origin + "/"}
            return LiveStream(url, headers)
        raise LiveError(_UNSUPPORTED)


_PROBE_LOGIN_JS = """
async ({origin, apiPath}) => {
    if (location.origin !== origin) return {ok: false};
    const keys = Object.keys(sessionStorage).filter(k => k.endsWith("_STORAGE_KEY_JWT_TOKEN"));
    const jwt = keys.length === 1 ? sessionStorage.getItem(keys[0]) || "" : "";
    const headers = {"Accept": "application/json"};
    if (jwt) headers["jwt-token"] = jwt;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
        const response = await fetch(apiPath, {
            method: "GET", credentials: "include", redirect: "error",
            headers, signal: controller.signal
        });
        if (response.status !== 200) return {ok: false};
        const body = await response.json();
        return {ok: !!body && body.ok === true && body.status === 200 &&
                    !!body.data && body.data.id !== undefined &&
                    body.data.id !== null && String(body.data.id).trim() !== "",
                jwt_token: jwt};
    } catch (_) {
        return {ok: false};
    } finally {
        clearTimeout(timer);
    }
}
"""


def _block_viewing_writes(route) -> None:
    """Login may visit a list page, but must not generate playback telemetry."""
    request = route.request
    parsed = _url(request.url)
    path = parsed.path if parsed is not None else ""
    blocked = (parsed is not None and parsed.hostname in _SITE_HOSTS
               and request.method.upper() not in ("GET", "HEAD", "OPTIONS")
               and (path.startswith(_API + "/v1/live/")
                    or path.startswith(_API + "/v1/vod/")
                    or path in (_API + "/v1/data/reporting",
                                _API + "/v1/statistics/visitRecord/create")))
    route.abort() if blocked else route.continue_()


def _saved_manual_login(origin: str) -> bool:
    try:
        saved = json.loads((application_root() / "live_session.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return (isinstance(saved, dict) and saved.get("origin") == origin
            and saved.get("login_mode") == "manual")


def _save_session(origin: str, cookies: list[dict], jwt: str,
                  *, login_mode: str | None = None) -> None:
    root = application_root()
    temporary = None
    failed = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=".live-session-", suffix=".json", dir=root)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            saved = {"version": 1, "origin": origin, "captured_at": time.time(),
                     "cookies": cookies, "jwt_token": jwt}
            if login_mode == "manual":
                saved["login_mode"] = "manual"
            json.dump(saved, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "live_session.json")
    except (OSError, ValueError):
        failed = True
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                failed = True
    if failed:
        raise LiveError("无法保存直播登录资料，请检查程序目录的写入权限。")


def login_live(page_url: str, stop=None, *, switch_account: bool = False) -> int:
    """Keep manual account selection on later logins without reusing old profiles."""
    origin, _ = parse_live_page(page_url)
    if stop is not None and stop.is_set():
        print("直播登录已取消。")
        return 1
    manual_login = switch_account or _saved_manual_login(origin)
    from echosign import browser

    configure_browser_runtime()
    context = None
    live_browser = None
    try:
        with sync_playwright() as playwright:
            try:
                if manual_login:
                    live_browser = playwright.chromium.launch(
                        headless=False, args=browser._browser_args(), timeout=30000)
                    context = live_browser.new_context()
                    print("请在新窗口手动登录要使用的直播账号。")
                else:
                    context = playwright.chromium.launch_persistent_context(
                        str(application_root() / "live_profile"), headless=False,
                        args=browser._browser_args(), timeout=30000)
                context.route("**/*", _block_viewing_writes)
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(origin + "/#/list-live", wait_until="domcontentloaded", timeout=10000)
                except PlaywrightError:
                    pass
                deadline = time.monotonic() + _LOGIN_TIMEOUT_SECONDS
                attempted = False
                fill_attempts = 0
                while time.monotonic() < deadline:
                    if stop is not None and stop.is_set():
                        print("直播登录已取消。")
                        return 1
                    if page.is_closed():
                        print("直播登录窗口已关闭，尚未保存登录。")
                        return 1
                    current = _url(page.url)
                    if (current is not None and current.scheme == "https"
                            and current.port in (None, 443) and current.hostname in _SSO_HOSTS):
                        if not manual_login and not attempted and fill_attempts < 2:
                            try:
                                page.wait_for_selector("input[type=password]", timeout=1000)
                                secrets = browser.load_secrets()
                                ready = _url(page.url)
                                if (ready is not None and ready.scheme == "https"
                                        and ready.port in (None, 443)
                                        and ready.hostname in _SSO_HOSTS
                                        and (stop is None or not stop.is_set())):
                                    fill_attempts += 1
                                    attempted = browser.try_sso_login(page, secrets)
                            except PlaywrightError:
                                pass
                            except (Exception, SystemExit):
                                attempted = True
                                print("请在直播登录窗口中完成登录和验证码。")
                    elif (current is not None and current.scheme == "https"
                          and current.port in (None, 443)
                          and current.hostname in _SITE_HOSTS
                          and "https://" + current.hostname == origin):
                        try:
                            result = page.evaluate(_PROBE_LOGIN_JS, {
                                "origin": origin, "apiPath": _API + "/v1/currentuser"})
                            if stop is not None and stop.is_set():
                                print("直播登录已取消。")
                                return 1
                            if isinstance(result, dict) and result.get("ok") is True:
                                jwt = result.get("jwt_token", "")
                                cookies = _cookies_for_origin(context.cookies(
                                    [origin + "/", origin + _API + "/v1/currentuser"]), origin)
                                if stop is not None and stop.is_set():
                                    print("直播登录已取消。")
                                    return 1
                                if _plain(jwt) and jwt.isascii() and (jwt or cookies):
                                    _save_session(origin, cookies, jwt,
                                                  login_mode="manual" if manual_login else None)
                                    print("直播登录已保存，可启动后台音频监控。")
                                    return 0
                        except PlaywrightError:
                            pass
                    page.wait_for_timeout(250)
                print("直播登录超时，请重新点击“登录直播”并完成验证。")
                return 1
            finally:
                try:
                    if context is not None:
                        try:
                            context.close()
                        except PlaywrightError:
                            pass
                finally:
                    if live_browser is not None:
                        try:
                            live_browser.close()
                        except PlaywrightError:
                            pass
    except PlaywrightError:
        pass
    if stop is not None and stop.is_set():
        print("直播登录已取消。")
        return 1
    raise LiveError("无法完成直播登录，请关闭之前的直播登录窗口后重试。")

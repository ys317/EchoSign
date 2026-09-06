"""Structured browser sign-in results, independent of human-readable logs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class SignResult:
    status: str
    sign_code: str
    message: str

    @property
    def exit_code(self) -> int:
        return {"success": 0, "failure": 1, "unknown": 2}[self.status]

    def write(self, path: Path) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def read(cls, path: Path, sign_code: str) -> SignResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict)
                or data.get("status") not in ("success", "failure", "unknown")
                or data.get("sign_code") != sign_code
                or not isinstance(data.get("message"), str)):
            raise ValueError("签到结果格式无效或签到码不匹配")
        return cls(data["status"], sign_code, data["message"][:240])


def classify_response(sign_code: str, http_status: int, payload: object) -> SignResult:
    """Interpret the business code from the matched HDU sign-in endpoint only.

    HTTP 200, captcha/login responses and arbitrary log text do not prove a sign-in.
    Missing or unrecognized response schemas remain unknown.
    """
    if not 200 <= http_status < 300:
        return SignResult("failure", sign_code, f"签到接口返回 HTTP {http_status}")
    if not isinstance(payload, dict):
        return SignResult("unknown", sign_code, "签到接口未返回可识别的 JSON 结果")
    message = payload.get("msg") or payload.get("message")
    message = " ".join(message.split())[:240] if isinstance(message, str) else ""
    business_code = payload.get("code")
    if type(business_code) not in (int, str):
        return SignResult("unknown", sign_code, "签到响应缺少有效的业务状态码")
    if business_code in (200, "200") and payload.get("success") is not False:
        return SignResult("success", sign_code, message or "签到接口已确认成功")
    return SignResult("failure", sign_code, message or f"签到接口返回业务状态 {business_code}")

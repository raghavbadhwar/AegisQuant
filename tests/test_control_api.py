import asyncio

from aegisquant.control_api import app, ready


def test_m0_health_declares_safety_boundary() -> None:
    status = asyncio.run(ready())
    assert status.model_dump(mode="json") == {
        "status": "ok",
        "milestone": "M0_SECURITY_KERNEL",
        "live_trading_enabled": False,
        "broker_adapter_present": False,
        "unrestricted_web_enabled": False,
    }


def test_m0_has_no_order_submission_route() -> None:
    paths = {route.path for route in app.routes}
    assert not any("order" in path.lower() or "broker" in path.lower() for path in paths)

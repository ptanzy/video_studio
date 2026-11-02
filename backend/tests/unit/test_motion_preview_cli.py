from wrld_video_studio.domain.media_errors import MediaInfrastructureError
from wrld_video_studio.interfaces.cli.motion_preview import _close_preview_resources


class FailingClose:
    def __init__(self, code):
        self.code = code
        self.called = 0

    def close(self):
        self.called += 1
        raise MediaInfrastructureError(self.code, "Cleanup failed.")


def test_preview_cli_cleanup_attempts_service_after_lease_failure_and_keeps_first_error():
    lease = FailingClose("LEASE_CLEANUP_FAILED")
    service = FailingClose("SERVICE_CLEANUP_FAILED")

    error = _close_preview_resources(lease, service)

    assert error is not None
    assert error.code == "LEASE_CLEANUP_FAILED"
    assert lease.called == service.called == 1


def test_preview_cli_cleanup_returns_service_failure_when_lease_succeeds():
    class SuccessfulClose:
        def close(self):
            return None

    service = FailingClose("SERVICE_CLEANUP_FAILED")

    error = _close_preview_resources(SuccessfulClose(), service)

    assert error is not None
    assert error.code == "SERVICE_CLEANUP_FAILED"

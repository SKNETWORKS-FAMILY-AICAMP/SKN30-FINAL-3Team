from brokerage_ai.f3 import InputPrivacyMode, NegotiationSide
from brokerage_ai.smoke import synthetic_requests


def test_serving_smoke_uses_valid_synthetic_opposite_sides() -> None:
    listing, requirement = synthetic_requests()
    assert listing.negotiation_side is NegotiationSide.LISTING
    assert requirement.negotiation_side is NegotiationSide.REQUIREMENT
    for request in (listing, requirement):
        assert request.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
        assert not request.consultation_logs
        assert request.source.interaction_count == 0

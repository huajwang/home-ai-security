from hub.devices.doorbell import visitor_state


def test_visitor_rising_edge() -> None:
    assert visitor_state("tns1:RuleEngine/MyRuleDetector/Visitor", {"State": "true"}) is True
    assert visitor_state("tns1:RuleEngine/MyRuleDetector/Visitor", {"State": "false"}) is False
    assert visitor_state("tns1:RuleEngine/MyRuleDetector/PeopleDetect", {"State": "true"}) is None

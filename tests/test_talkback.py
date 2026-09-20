import numpy as np

from hub.devices.talkback import linear_to_ulaw, parse_backchannel, redact_rtsp


def test_parse_reolink_sendonly_pcmu() -> None:
    sdp = (
        "v=0\n"
        "m=video 0 RTP/AVP 96\n"
        "a=recvonly\n"
        "a=control:track1\n"
        "m=audio 0 RTP/AVP 97\n"
        "a=rtpmap:97 MPEG4-GENERIC/16000\n"
        "a=recvonly\n"
        "a=control:track2\n"
        "m=audio 0 RTP/AVP 0\n"
        "a=control:track3\n"
        "a=rtpmap:0 PCMU/8000\n"
        "a=sendonly\n"
    )
    back = parse_backchannel(sdp, "rtsp://10.0.0.112:554/h264Preview_01_sub")
    assert back is not None
    assert back.payload_type == 0
    assert back.encoding == "PCMU"
    assert back.control.endswith("/track3")


def test_ulaw_silence() -> None:
    encoded = linear_to_ulaw(np.zeros(8, dtype=np.int16))
    assert encoded == b"\xff" * 8


def test_redact_rtsp() -> None:
    assert redact_rtsp("rtsp://admin:secret@10.0.0.112:554/h264Preview_01_sub") == (
        "rtsp://***@10.0.0.112:554/h264Preview_01_sub"
    )

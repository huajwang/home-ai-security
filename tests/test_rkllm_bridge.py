"""Unit tests for RKLLM CTypes bridge."""

from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

from hub.ai.rkllm_bridge import (
    LLMCallState,
    RKLLMCallback,
    RKLLMInput,
    RKLLMParam,
    RKLLMResult,
    RKLLMRunner,
    format_chatml,
    get_runner,
)


def test_format_chatml():
    messages = [
        {"role": "system", "content": "You are a home security assistant."},
        {"role": "user", "content": "Who is at the door?"},
    ]
    prompt = format_chatml(messages)
    assert "<|im_start|>system\nYou are a home security assistant.<|im_end|>\n" in prompt
    assert "<|im_start|>user\nWho is at the door?<|im_end|>\n" in prompt
    assert prompt.endswith("<|im_start|>assistant\n")


def test_runner_unavailable_when_model_missing(tmp_path):
    missing_model = str(tmp_path / "non_existent.rkllm")
    runner = RKLLMRunner(model_path=missing_model, lib_path="non_existent_lib.so", auto_init=True)
    assert not runner.is_available
    assert runner.generate("Hello") == ""
    assert runner.chat([{"role": "user", "content": "Hi"}]) == ""
    runner.close()


def test_runner_mock_lifecycle():
    fake_lib = MagicMock()

    def mock_init(handle_ptr, param_ptr, cb_ptr):
        handle_ptr._obj.value = 0x12345678
        return 0

    fake_lib.rkllm_init.side_effect = mock_init
    fake_lib.rkllm_run.return_value = 0
    fake_lib.rkllm_destroy.return_value = 0

    with patch("os.path.exists", return_value=True), patch("ctypes.CDLL", return_value=fake_lib):
        runner = RKLLMRunner(
            model_path="/dummy/model.rkllm",
            lib_path="/dummy/lib.so",
            auto_init=False,
        )
        assert not runner.is_available
        assert runner.initialize() is True
        assert runner.is_available is True

        # Simulate a token response in callback
        def mock_run(handle, inp, infer_param, userdata):
            # simulate callback invocations
            cb_fn = runner._callback_holder
            res1 = RKLLMResult()
            res1.text = b"Hello, "
            cb_fn(ctypes.byref(res1), None, LLMCallState.RKLLM_RUN_NORMAL)

            res2 = RKLLMResult()
            res2.text = b"homeowner!"
            cb_fn(ctypes.byref(res2), None, LLMCallState.RKLLM_RUN_NORMAL)

            cb_fn(None, None, LLMCallState.RKLLM_RUN_FINISH)
            return 0

        fake_lib.rkllm_run.side_effect = mock_run

        resp = runner.generate("Hi")
        assert resp == "Hello, homeowner!"

        runner.close()
        assert not runner.is_available
        fake_lib.rkllm_destroy.assert_called_once()
